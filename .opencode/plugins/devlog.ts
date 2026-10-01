/**
 * Devlog plugin — appends a summary of each finished turn to docs/devlog/YYYY-MM-DD.md
 *
 * Fires on `session.idle` (the closest event to "session ended": the agent
 * finished responding and the session went quiet). Everything the session did
 * since the last logged write is summarized: user prompt, tools used (edits,
 * commands), and the final assistant reply.
 *
 * Files touched are collected from edit/write tool parts; a cursor per session
 * prevents duplicate entries across repeated idle events.
 */
import type { Plugin } from "@opencode-ai/plugin"
import { mkdir, readFile, appendFile } from "node:fs/promises"
import path from "node:path"

type AnyPart = {
  type?: string
  tool?: string
  state?: { title?: string; output?: string }
  text?: string
}

type AnyMessage = {
  info?: { id?: string; role?: string; sessionID?: string }
  parts?: AnyPart[]
}

const MAX_PROMPT = 160
const MAX_SUMMARY = 400
const MAX_ITEMS = 12

const truncate = (s: string | undefined, n: number) => {
  const t = (s ?? "").replace(/\s+/g, " ").trim()
  return t.length > n ? t.slice(0, n - 1) + "…" : t
}

export const DevlogPlugin: Plugin = async ({ client, directory, worktree }) => {
  const root = worktree ?? directory ?? process.cwd()
  const devlogDir = path.join(root, "docs", "devlog")
  // sessionID -> last message id already written to the devlog
  const cursor = new Map<string, string>()

  const localDate = () => {
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }

  const devlogFile = async () => {
    const date = localDate()
    const file = path.join(devlogDir, `${date}.md`)
    try {
      await readFile(file, "utf8")
    } catch {
      await mkdir(devlogDir, { recursive: true })
      await appendFile(file, `# ${date}\n`)
    }
    return file
  }

  const summarize = (session: { title?: string; id: string }, newMsgs: AnyMessage[]) => {
    const now = new Date().toTimeString().slice(0, 5)
    const prompts: string[] = []
    const did: string[] = []
    let lastReply = ""

    for (const m of newMsgs) {
      const role = m.info?.role
      for (const p of m.parts ?? []) {
        if (p.type === "text") {
          if (role === "user") prompts.push(truncate(p.text, MAX_PROMPT))
          if (role === "assistant" && p.text?.trim()) lastReply = p.text
        }
        if (p.type === "tool" && p.tool) {
          const title = truncate(p.state?.title ?? p.tool, 80)
          did.push(`${p.tool}: ${title}`)
        }
      }
    }

    const lines = [`\n## ${now} — ${truncate(session.title ?? session.id, 60)} (\`${session.id}\`)`]
    for (const p of prompts.slice(0, 3)) lines.push(`- **Asked:** ${p}`)
    if (did.length) {
      lines.push(`- **Did:**`)
      for (const d of did.slice(0, MAX_ITEMS)) lines.push(`  - ${d}`)
      if (did.length > MAX_ITEMS) lines.push(`  - …${did.length - MAX_ITEMS} more`)
    }
    if (lastReply) lines.push(`- **Summary:** ${truncate(lastReply, MAX_SUMMARY)}`)
    return lines.join("\n") + "\n"
  }

  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      try {
        const sessionID = (event.properties as { sessionID?: string })?.sessionID
        if (!sessionID) return

        // SDK may return `{ data }` or the payload directly depending on response style
        const unwrap = <T,>(r: unknown): T =>
          r && typeof r === "object" && "data" in (r as Record<string, unknown>)
            ? ((r as { data: T }).data as T)
            : (r as T)

        const session = unwrap<{ title?: string; id?: string }>(
          await client.session.get({ path: { id: sessionID } }),
        )
        const msgs = unwrap<AnyMessage[]>(await client.session.messages({ path: { id: sessionID } }))
        if (!msgs?.length) return

        const sinceId = cursor.get(sessionID)
        const start = sinceId ? msgs.findIndex((m) => m.info?.id === sinceId) + 1 : 0
        const newMsgs: AnyMessage[] = msgs.slice(start < 0 ? 0 : start)
        if (!newMsgs.length) return

        // Only log turns that actually did something (a reply beyond bare acks)
        const hasContent = newMsgs.some(
          (m) =>
            m.info?.role === "assistant" &&
            (m.parts ?? []).some((p) => (p.type === "tool" && p.tool) || p.text?.trim()),
        )
        if (!hasContent) {
          cursor.set(sessionID, msgs[msgs.length - 1].info?.id ?? "")
          return
        }

        const file = await devlogFile()
        await appendFile(file, summarize({ title: session?.title, id: sessionID }, newMsgs))
        cursor.set(sessionID, msgs[msgs.length - 1].info?.id ?? "")

        await client.app.log({
          body: { service: "devlog-plugin", level: "info", message: `Logged turn for ${sessionID}` },
        })
      } catch (e) {
        await client.app
          .log({
            body: {
              service: "devlog-plugin",
              level: "warn",
              message: `Failed to append devlog: ${(e as Error).message}`,
            },
          })
          .catch(() => {})
      }
    },
  }
}
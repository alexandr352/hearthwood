---
key: LAN-4
title: Replay the queue when the connection returns
type: Task
status: Todo
parent: LAN-1
blocked_by: [LAN-3]
created: 2026-08-22
updated: 2026-09-30
---
When the app is back online, send the queued edits to the server in order and empty the queue.

Acceptance: the queue is empty and the server holds every edit after reconnecting.

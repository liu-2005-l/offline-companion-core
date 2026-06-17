# Offline Companion · User Manual v1.0 (English)

> **Date**: 2026-06-12 · **Audience**: end users · **中文**: [`USER_MANUAL_v1.0_zh.md`](./USER_MANUAL_v1.0_zh.md)

---

## What is this?

A **local-first** desktop companion. Chats and memories stay on your PC by default. Network use requires an explicit **consent card**.

---

## First launch

Open from Start menu or desktop icon. Layout: sidebar, chat area, footer (privacy, memory toggle, model status). Closing the window **minimizes to tray**; exit from tray menu. Re-launch **activates the existing window**.

> 📷 Screenshot placeholder: main window

---

## Chat

Type in the chat area and send. Assistant replies below.

---

## Memory

Memory is **off by default**. To save a fact, send a line starting with `#remember` followed by the text (e.g. `#remember My name is Master`). Clear the thread and ask your name to verify. Toggle memory in the **footer**.

> 📷 Screenshot placeholder: memory toggle

---

## Privacy

**Local only** mode blocks extensions that need the network without silent egress.

---

## Mods (extensions)

Open **Mod Marketplace** from the sidebar or Settings. Browse unified cards with name, description, and rating. Filters: All / Capability / Interaction / Tool. Install or uninstall in one tap; enable/disable in Settings. New mods are **disabled** until you turn them on. The mall is optional; local folder install works the same way for developers.

Voice input/output: see Chinese manual §六 (planned Sprint 8).

---

## Safety

Crisis phrases trigger **fixed safety replies** that users cannot override in chat.

---

## Quick acceptance checklist

Hello → reply · `#remember` name test · footer visible · tray single instance · crisis phrase → safety reply.

Developers: see repo README and ARCHITECTURE for commands.

**Authority**: Chinese manual on ambiguity.

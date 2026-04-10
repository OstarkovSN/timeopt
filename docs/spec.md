# Task Planner — Claude Code Plugin

## Overview

A Claude Code plugin that lets me brain-dump tasks in plain text, stores them persistently, and helps me organize my day. Integrates with Yandex Calendar so it can plan around existing meetings and events.


## Features

### 1. Brain Dump

I type tasks in messy free-form text and the plugin parses them into structured tasks. It should infer priority, category, and due date when possible.

Example input:
> fix login bug, call dentist, prep slides for thursday, buy groceries, urgent: deploy hotfix before noon

Expected behavior:
- Parses each item as a separate task
- "urgent" and "before noon" → high priority + due date
- "for thursday" → due date set to next Thursday
- Categories guessed from context (work, personal, errands)

### 2. View Tasks

Show all pending tasks grouped by priority (high → medium → low). Include due dates, categories, and age (how long ago the task was created).

### 3. Daily Planner

Analyze all pending tasks and suggest a realistic time-blocked schedule for the day.

- Ask what time my day starts and ends
- Check Yandex Calendar for existing meetings/events
- Fit tasks into free slots around calendar commitments
- Apply Eisenhower matrix: urgent + important first
- Estimate effort per task (small/medium/large)
- Include breaks — don't pack the day wall-to-wall
- Flag overloaded days: "You have ~10 hours of work but only 6 free hours — what should move to tomorrow?"

### 4. Mark Done

Let me check off one or more tasks as completed. Keep a log of completed tasks with timestamps.

### 5. Persistence

Tasks must survive across sessions. Use whatever storage makes sense for the architecture — database, local server, file-based. Unfinished tasks carry over automatically. No manual "reload" needed.

### 6. Yandex Calendar Integration

Connect to Yandex Calendar via CalDAV so the planner can:
- Fetch today's (and upcoming) events and meetings
- Show free/busy time slots when planning
- Warn about scheduling conflicts
- Optionally push planned task blocks back to the calendar

Yandex Calendar CalDAV endpoint: `https://caldav.yandex.ru`

Authentication will need an app-specific password from Yandex.

### 7. Easy on/off toggle

All my meetings and tasks will surely overflow your context window, so the plugin should be turned off for regular projects.

## Design Principles

- **Forgiving parsing** — I'll write sloppily, it should just work
- **Eisenhower matrix** — prioritize by urgent × important
- **Breaks matter** — suggest breaks in the daily plan
- **Calendar-first planning** — always check calendar before scheduling tasks
- **Solid architecture** — server, database, whatever makes it maintainable. No constraints on complexity.

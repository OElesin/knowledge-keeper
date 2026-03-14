---
inclusion: always
---

# KnowledgeKeeper — Product Overview

## What It Is

KnowledgeKeeper is an open-source, self-hosted platform that transforms departing employees' email archives into persistent, queryable AI-powered knowledge bases — referred to as **digital twins**. It is triggered by IT Admins as part of standard employee offboarding.

## The Problem It Solves

Organizations lose critical institutional knowledge when employees leave. Email threads, decisions, workarounds, and system context exist in employees' inboxes but become inaccessible after departure. Existing knowledge management tools require intentional documentation that rarely happens under pressure.

## How It Works (User-Facing)

1. IT Admin triggers offboarding for a departing employee in the admin dashboard
2. System ingests their email archive from Google Workspace or Microsoft 365
3. Emails are processed, cleaned, chunked, and embedded into a vector store
4. A **digital twin** is created — a queryable knowledge profile for that employee
5. Authorized colleagues query the twin in natural language via the query interface
6. Responses are grounded in the employee's actual communications, with source citations, confidence scores, and staleness warnings

## Core Personas

- **IT Admin** — triggers offboarding, manages twin lifecycle, configures retention policies
- **Engineering Manager / Team Lead** — queries twins to recover context after employee departures
- **New Joiners** — use twins to onboard faster into existing systems and decisions
- **CISO / Legal** — review audit logs, configure PII policies, manage data retention

## Key Differentiators

- **Self-hosted on AWS** — data never leaves the customer's own AWS account
- **Fully serverless** — no infrastructure to manage; pay-per-use cost model
- **Open source** — fully auditable codebase; designed for security-conscious enterprises
- **Noise-aware ingestion** — thread reconstruction, PII detection, and relevance scoring before indexing
- **Access-controlled twins** — scoped authorization per twin per user role

## What It Is Not

- Not a real-time chat interface with the departed employee
- Not a replacement for proper documentation practices
- Not a SaaS product; all data stays in the customer's AWS account
- Not a surveillance tool — consent and policy templates are included

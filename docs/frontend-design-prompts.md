# KnowledgeKeeper — Frontend Design Prompts (Google Stitch)

Use these prompts in Google Stitch (or any AI design tool) to generate UI mockups for the three main pages.

---

## Prompt 1: Admin Dashboard

Design a clean, modern admin dashboard for an internal IT tool called "KnowledgeKeeper". The page has two sections:

Top section: A data table listing digital twins of departed employees. Columns: Employee Name, Department, Status (color-coded pill badges — green for "active", yellow for "processing", blue for "ingesting", red for "error"), Offboard Date, and Chunk Count. Include a search/filter bar above the table.

Bottom section: An offboarding form card with fields for Employee ID, Full Name, Email, Role, Department, Offboard Date, and a radio group for email provider (Google Workspace / File Upload). A primary "Start Ingestion" button at the bottom.

Style: Minimal enterprise SaaS aesthetic. White background, subtle gray borders, TailwindCSS-style spacing. Left sidebar nav with icons for Dashboard, Twins, and Settings. Use a dark navy top bar with the app name "KnowledgeKeeper" and a user avatar.

---

## Prompt 2: Twin Detail

Design a detail page for a single digital twin in an internal IT tool called "KnowledgeKeeper". The page shows:

Top: A header card with the employee's name, email, role, department, offboard date, status badge (green "active" pill), and chunk count stat.

Middle: An "Access Control" section with a table of authorized users. Columns: User ID, Role (admin/viewer dropdown), and a red "Revoke" button per row. Below the table, a compact inline form to grant access: User ID text input, Role dropdown, and a "Grant Access" button.

Bottom: A danger zone card with a red outlined "Delete Twin" button and a warning message about permanent data removal.

Style: Same minimal enterprise SaaS look. White cards with subtle shadows, consistent with TailwindCSS spacing. Left sidebar nav. Breadcrumb navigation at the top: Dashboard > Twins > Jane Smith.

---

## Prompt 3: Query Interface

Design a chat-style query interface for an internal knowledge retrieval tool called "KnowledgeKeeper". The user is querying a departed employee's digital twin.

Top: A compact header showing the twin's name ("Jane Smith — Senior SRE") and a green "active" status badge.

Center: A chat-style conversation area. The user's query appears as a right-aligned bubble. The AI response appears as a left-aligned card with: the answer text with inline citation markers like [1] [2], a horizontal confidence bar (e.g. 82% — green), and an expandable "Sources" section showing citation cards with date, email subject, and a short content preview. Include an orange "staleness warning" banner above the answer if sources are old.

Bottom: A fixed input bar with a text field ("Ask a question about Jane's knowledge...") and a send button.

Style: Clean, conversational UI. White background, light gray chat bubbles for AI, blue bubbles for user. TailwindCSS spacing. Left sidebar nav consistent with the other pages.

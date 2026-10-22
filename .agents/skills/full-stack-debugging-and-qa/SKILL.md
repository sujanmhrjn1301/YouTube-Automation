---
name: full-stack-debugging-and-qa
description: Industry-standard full-stack debugging and Quality Assurance (QA) workflow for web applications, APIs, background workers, and interactive user journeys. Use to systematically trace, diagnose, and verify every user interaction from entering data to clearing, submitting, state mutations, and edge-case handling.
---

# Full-Stack Debugging and QA Framework

This skill outlines an end-to-end, rigorous methodology for auditing, debugging, and performing quality assurance across frontend interfaces, API endpoints, state management, background daemons, and database persistence.

---

## 1. The 4-Phase Diagnostic Methodology

### Phase 1: Interaction & Event Triangulation
When examining any user interaction (e.g. typing, clicking a button, selecting a tab, clicking clear, toggling a switch):
1. **User Intent vs. Actual Trigger**:
   - Verify which DOM element receives the click or input event.
   - Check if event listeners are attached properly (`addEventListener`, inline handlers, or delegated listeners).
   - Ensure `stopPropagation()` or `preventDefault()` are used intentionally and not blocking expected bubble flows or default behaviors.
2. **Input Lifecycle & Clearing**:
   - **Enter Phase**: Does typing trigger live validation, input sanitization, or live preview updates?
   - **Clear Phase**: Does clearing an input (via Backspace, native clear, or custom `×` clear button):
     - Clear the input value in the DOM?
     - Clear bound internal state/variables?
     - Clear associated preview panels, statuses, live monitors, and downstream UI indicators?
     - Restore placeholder states or hide error banners?
   - **Submit Phase**: Does clicking submit validate required fields, show immediate loading feedback (spinners, disabled buttons), and prevent duplicate submissions?

### Phase 2: Layer-by-Layer Boundary Isolation
When a bug or mismatch occurs, isolate where the chain breaks:
1. **UI / DOM Layer**:
   - Inspect console logs, unhandled promise rejections, and runtime JavaScript exceptions.
   - Verify dynamic DOM replacement doesn't strip or re-bind event listeners multiple times.
   - Check element accessibility, visibility, disabled states, and z-index modal layering.
2. **Network / Fetch API Layer**:
   - Verify exact HTTP method, path, headers (`Content-Type: application/json`), and request payload.
   - Verify response status code (200, 400, 422, 500) and response schema.
   - Check timeout handling, CORS issues, and network failure gracefully caught by `catch()` blocks.
3. **Backend Service & Daemon Layer**:
   - Verify route handlers parse payloads securely and validate types.
   - Ensure background tasks (subprocesses, threads, async queues) do not crash silently.
   - Validate process concurrency, port availability, and standard error logging.
4. **Data Persistence Layer (SQLite / Supabase / Cache)**:
   - Check schema mismatches, null constraints, and missing default values.
   - Verify multi-database fallbacks (e.g. local SQLite fallback when cloud Supabase is offline or vice-versa).
   - Verify consistency across data models (e.g. status enum matching between frontend UI and database rows).

### Phase 3: Interactive Click-by-Click QA Checklist
Every view and user path must be audited against:

| Interaction Category | QA Checkpoints |
| :--- | :--- |
| **Navigation & Tabs** | Click each nav link/hash: Does view switch instantly? Does active state highlight? Does history hash persist? |
| **Input Fields** | Type valid, invalid, and empty strings. Is whitespace trimmed? Are special characters handled? |
| **Clear Controls (`×`)**| Click clear button: Does it wipe input text? Does it focus back or blur cleanly? Does it reset dependent state/cards? |
| **Toggles & Switches** | Click checkbox/toggle: Does visual toggle state match boolean variable? Does label click toggle the control? |
| **Segmented Buttons** | Click option: Does only one remain active? Does data attribute match backend parameters? |
| **Modals & Popovers** | Open modal: Does backdrop appear? Does ESC key or outside click close it? Does submit close and refresh data? |
| **Error Handling** | Force bad inputs: Does UI show actionable error messages instead of silent freezes? |
| **Live Polling / Updates** | Check background polling: Does it update DOM smoothly without jitter, memory leaks, or focus loss? |

### Phase 4: Verification, Regression Guard & Reporting
1. **Reproduce & Isolate**: Pinpoint the exact file, line number, and trigger sequence.
2. **Minimal Surgical Remediation**: Fix the root cause without side-effects or regressions in adjacent components.
3. **Live End-to-End Validation**: Walk through the user flow in the real browser, verifying visual and functional correctness.
4. **Structured QA Report**: Document all findings categorized into Major, Minor, UI/UX Polish, and Pass status.

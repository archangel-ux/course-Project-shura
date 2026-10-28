# Claude Code үшін алғашқы промпт

Read `CLAUDE.md`, `PROJECT_OVERVIEW.md`, and `README.md` carefully before making changes.

First inspect the current project folder and identify whether a Python project already exists. Do not overwrite or delete existing files. This project must use Python only — no Java, JavaFX, Spring Boot, or other Java technologies.

The application is a desktop inventory-management system for recording products, stock-in and stock-out operations, current quantities, low-stock warnings, and CSV exports. Use Python 3.11+, CustomTkinter for the GUI, and SQLite through Python's built-in `sqlite3` module. Do not add external APIs, cloud databases, web servers, or mobile features.

Do not build the entire application in one step. First:
1. Summarize the current project state.
2. Propose a simple, beginner-friendly folder structure.
3. List the required dependencies and explain why each is needed.
4. Describe the first milestone and the files it will create or modify.
5. Point out any unclear requirements before making assumptions.

Wait before implementing the full application. Keep code easy to understand, use Kazakh for the UI, validate inputs, use parameterized SQL, and ensure stock quantities cannot become negative. After each milestone, explain how to run and test the work.

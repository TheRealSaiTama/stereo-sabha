# Repository Guidelines

## Project Structure & Module Organization

This repository is currently empty: no source code, tests, assets, dependency manifests, or Git metadata are present. Establish the layout with the first implementation and document it in `README.md`. Prefer clear directories such as `src/` for application code, `tests/` for automated tests, and `assets/` for static resources when appropriate. Organize modules by responsibility and keep related files together.

## Build, Test, and Development Commands

No build, test, or local development commands are configured yet. When introducing a toolchain, add a dependency manifest and document exact installation, run, build, and test commands in `README.md`. Run commands from the repository root unless documented otherwise. Do not assume commands such as `npm test` or `make build` exist before their configuration is committed.

## Coding Style & Naming Conventions

Follow the chosen language’s standard conventions. Configure formatting and linting with the first source files, then use those tools consistently. Keep indentation consistent within each language and avoid unrelated formatting changes. Use descriptive names for modules, functions, and variables; keep filenames consistent with the selected framework. Favor small functions and explicit interfaces over speculative abstractions.

## Testing Guidelines

No testing framework or coverage threshold is established. Select a framework appropriate to the implementation and document how to run it. Add tests for new behavior and regression tests for bug fixes. Use descriptive test names that identify the behavior and expected result. Keep tests deterministic; isolate external services and avoid requiring production credentials.

## Commit & Pull Request Guidelines

No Git history is available to establish existing commit conventions. Use concise, imperative subjects, such as `Add local development setup`, and keep each commit focused. Pull requests should explain the problem, summarize the change, and list validation performed. Link relevant issues and include screenshots for visible UI changes. Explicitly identify setup changes and any checks that could not be run.

## Security & Configuration

Keep credentials and local environment files out of version control. Provide placeholder configuration in `.env.example` when environment variables are introduced, and document required values without including secrets.

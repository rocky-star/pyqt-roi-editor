# AGENTS.md

- Use `uv` for the environment, dependencies and every tool invocation, e.g.
  `uv run basedpyright`, `uv run ruff check`.
- Use `basedpyright` for type checking.
- Use `Ruff` as a linter only; never as a formatter, and never enable
  `ruff format` or any of its formatting rules.
- Do not reformat automatically; follow the style, layout and naming of the
  existing code.
- This project uses PySide6 with
  `from __feature__ import snake_case, true_property`, so mind the interface
  differences: snake_case members, properties read and written directly
  instead of `setX()`/`x()` pairs, and signals connected to plain callables
  and bound methods instead of `SLOT()` strings; consult the docs of the
  feature import when the API shape is unclear.
- Write the first line of a commit message as an imperative sentence, with no
  Conventional Commits prefix, and with no issue reference in it.
- Explain a commit too complex to be obvious from its diff in the body, in
  multiple paragraphs rather than a list, saying what changed and why.
- Keep the message to what the diff cannot show; a body that only repeats
  the changes is noise, so leave the message at its first line instead.
- Put issue references only at the very end of the body, as a trailer
  separated from the rest of the body by a blank line, in one of these two
  forms, each with a comma-separated list of `#<issue>` references:

  ```text
  Resolves: #<issue>, #<issue>, [...]
  See Also: #<issue>, #<issue>, [...]
  ```
- Wrap prose (comments, docstrings, Markdown, reST, and so on) where it reads
  best: after a sentence, after a clause, after a long phrase, and so on.
- Respect these column limits: code 79; block comments and docstrings 72;
  Markdown and reST 80; commit message subject 50; commit message body 72.
- Treat those limits as soft: never break a URL, an identifier or similar
  unsplittable token just to stay under them.
- Quote human-readable strings in code with double quotes, e.g. label texts
  and message-box texts.
- Quote everything else with single quotes, e.g. identifiers and the names of
  command-line options.

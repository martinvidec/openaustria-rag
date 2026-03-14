---
name: github-workflow
description: GitHub Flow Workflow-Manager für Issue-basierte Entwicklung. Aktiviere diesen Skill automatisch beim Start einer neuen Session in einem Git-Repository mit GitHub-Remote. Lädt offene Issues, ermöglicht Auswahl, erstellt Feature-Branches pro Issue und arbeitet mit Pull Requests. Verwende auch wenn der Benutzer neue Issues erstellen möchte.
---

# GitHub Workflow

Workflow für Issue-basierte Entwicklung mit GitHub Flow.

## Session-Start in GitHub-Repo

Bei Session-Start in einem Git-Repo mit GitHub-Remote:

1. **Repo-Status prüfen**
   ```bash
   git remote -v
   gh repo view --json nameWithOwner -q .nameWithOwner
   ```

2. **Offene Issues laden und präsentieren**
   ```bash
   gh issue list --state open --limit 20 --json number,title,labels,assignees,createdAt
   ```

3. **Issues mit AskUserQuestion präsentieren** - Sortiert nach Priorität:
   - Issues mit Label `priority:high` oder `urgent` zuerst
   - Issues die dem Benutzer zugewiesen sind
   - Älteste Issues (länger offen)
   - Neueste Issues

4. **Nach Auswahl: Branch erstellen und wechseln**
   ```bash
   git checkout -b feature/<issue-nummer>-<kurzbeschreibung>
   ```
   Branch-Naming: `feature/123-add-user-auth` (Kleinbuchstaben, Bindestriche)

## Arbeiten an einem Issue

1. **Issue-Details laden** vor Beginn der Arbeit:
   ```bash
   gh issue view <nummer> --json title,body,comments,labels
   ```

2. **Regelmäßig committen** mit Referenz zum Issue:
   ```
   feat: Add login form validation

   Implements validation for #123
   ```

3. **Bei Fertigstellung: Pull Request erstellen**
   ```bash
   gh pr create --title "<titel>" --body "$(cat <<'EOF'
   ## Summary
   <Zusammenfassung der Änderungen>

   Closes #<issue-nummer>

   ## Changes
   - <Änderung 1>
   - <Änderung 2>

   ## Test Plan
   - [ ] <Test 1>
   - [ ] <Test 2>
   EOF
   )"
   ```

## Neues Issue erstellen

Verwende das Template aus [references/issue-template.md](references/issue-template.md).

```bash
gh issue create --title "<titel>" --body "$(cat <<'EOF'
<template-inhalt>
EOF
)"
```

Pflichtfelder:
- **Titel**: Kurz, prägnant, im Imperativ ("Add feature X", nicht "Adding feature X")
- **Beschreibung**: Was soll erreicht werden?
- **Akzeptanzkriterien**: Wann ist das Issue erledigt?

## Branch wechseln / Issue wechseln

Wenn der Benutzer zu einem anderen Issue wechseln möchte:

1. Aktuelle Änderungen committen oder stashen
2. Offene Issues erneut präsentieren
3. Neuen Branch erstellen oder zu bestehendem wechseln:
   ```bash
   git checkout feature/<issue-nummer>-<beschreibung>
   ```

## Konventionen

| Element | Format | Beispiel |
|---------|--------|----------|
| Branch | `feature/<nummer>-<beschreibung>` | `feature/42-user-login` |
| Bugfix-Branch | `fix/<nummer>-<beschreibung>` | `fix/99-null-pointer` |
| Commit | Conventional Commits | `feat: Add login (#42)` |
| PR-Titel | Beschreibend | `Add user authentication` |

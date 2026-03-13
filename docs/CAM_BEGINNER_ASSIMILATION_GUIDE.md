# CAM Beginner Assimilation Guide

This guide explains two different ways to use CAM with a folder of repositories:

1. use CAM to study repos and help create a new non-CAM application
2. use CAM to study repos so CAM itself assimilates the useful parts

## The Simple Idea

CAM can do two jobs:

- learn from repositories
- use what it learned to either improve itself or help build something new

The important point is that these are not the same workflow.

## Workflow 1: Use CAM To Help Create A New Non-CAM App

In this mode, CAM is acting like a research-and-builder assistant.

You give it a folder of example repos, and CAM:

1. studies them
2. extracts useful patterns
3. uses those patterns to help build a different application

That new application is not CAM. CAM is just the helper.

### Step 1: Mine The Source Repos

```bash
cam mine /path/to/folder-of-repos \
  --target /path/to/new-app \
  --max-repos 5 \
  --depth 3 \
  --max-minutes 20
```

What this means:

- `mine` tells CAM to study repositories
- `/path/to/folder-of-repos` is the folder CAM will search
- `--target /path/to/new-app` means "learn with this new app in mind"
- `--max-repos 5` limits how many repos CAM studies
- `--depth 3` limits how deep CAM searches through folders
- `--max-minutes 20` stops the run after 20 minutes

### Step 2: Inspect What CAM Learned

```bash
cam kb insights
cam kb search "test generation"
cam kb search "frontend scaffolding"
cam kb synergies
```

This helps you see:

- what capabilities CAM extracted
- what ideas appear reusable
- what patterns combine well across repos

### Step 3: Ask CAM To Create The New App

```bash
cam create /path/to/new-app \
  --repo-mode new \
  --request "Create a standalone app that does X using the strongest ideas learned from the mined repos" \
  --spec "Must be standalone" \
  --check "pytest -q" \
  --max-minutes 20
```

If you want CAM to attempt the changes immediately:

```bash
cam create /path/to/new-app \
  --repo-mode new \
  --request "Create a standalone app that does X using the strongest ideas learned from the mined repos" \
  --check "pytest -q" \
  --execute \
  --max-minutes 20
```

### Step 4: Validate The Result

```bash
cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

This checks whether CAM actually made what was requested.

## Workflow 2: Use CAM To Improve CAM Itself

In this mode, the goal is not to build a new app yet.

The goal is:

1. let CAM study outside repos
2. pull in useful ideas
3. keep those ideas in CAM's memory
4. make CAM better for later work

Think of this as training or enriching CAM.

### Step 1: Mine Repos For CAM's Benefit

```bash
cam mine /path/to/folder-of-repos \
  --target /path/to/cam \
  --max-repos 5 \
  --depth 3 \
  --max-minutes 20
```

Here the target is CAM itself, because the learning is meant to improve CAM.

### Step 2: Review What CAM Assimilated

```bash
cam kb insights
cam kb domains
cam kb synergies
cam kb search "debugging"
cam kb search "repo repair"
```

This helps answer:

- what useful capabilities were extracted
- which domains CAM now understands better
- which ideas from different repos combine well

### Step 3: Export What CAM Learned If Needed

```bash
cam forge-export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200 \
  --max-minutes 5
```

This creates a portable knowledge pack from CAM's learned material.

## The Difference In One Sentence

Use Workflow 1 if you want CAM to help build a new non-CAM app.

Use Workflow 2 if you want CAM itself to absorb useful ideas and get stronger for future tasks.

## Easy Mental Model

- `cam mine` = read and learn
- `cam kb ...` = inspect what was learned
- `cam create` = build something from that learning
- `cam validate` = check whether the build actually worked
- `cam forge-export` = package the learned knowledge for outside use

## Example

Suppose you have four repos about:

- code repair
- test generation
- deployment
- frontend UI

You can use CAM in two ways.

### Path A: Build A New App

CAM mines those repos, learns from them, and then helps create a brand new standalone app using the strongest ideas.

### Path B: Improve CAM

CAM mines those repos, keeps the useful patterns in memory, and later becomes better at fixing code, generating tests, deploying apps, and building UI.

## Best Practice

Run things in this order:

1. `cam mine`
2. `cam kb insights`
3. decide whether the learning is for CAM itself or for a new standalone app
4. run `cam create` only if you want CAM to build something
5. run `cam validate` before trusting the output

## Example Starter Commands

For a new app:

```bash
cam mine /path/to/folder-of-repos \
  --target /path/to/new-app \
  --max-repos 5 \
  --depth 3 \
  --max-minutes 20

cam kb insights

cam create /path/to/new-app \
  --repo-mode new \
  --request "Build a standalone app from the strongest ideas in the mined repos" \
  --check "pytest -q" \
  --max-minutes 20

cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

For improving CAM itself:

```bash
cam mine /path/to/folder-of-repos \
  --target /path/to/cam \
  --max-repos 5 \
  --depth 3 \
  --max-minutes 20

cam kb insights
cam kb synergies

cam forge-export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200 \
  --max-minutes 5
```

## Real Example Using `Repo2Eval`

Assume your repos are organized like this:

```text
/Volumes/WS4TB/Repo2Eval/
  repo-a/
  repo-b/
  repo-c/
```

And assume you want CAM either to:

1. help create a new standalone app in `/Volumes/WS4TB/new-app`
2. or assimilate the useful parts into CAM itself

### Real Example A: Use `Repo2Eval` To Help Build A New App

Step 1: mine the repos with the new app as the target

```bash
cam mine /Volumes/WS4TB/Repo2Eval \
  --target /Volumes/WS4TB/new-app \
  --max-repos 3 \
  --depth 2 \
  --max-minutes 20
```

Step 2: inspect what CAM learned

```bash
cam kb insights
cam kb search "testing"
cam kb search "frontend"
cam kb synergies
```

Step 3: ask CAM to create the new app

```bash
cam create /Volumes/WS4TB/new-app \
  --repo-mode new \
  --request "Build a standalone application using the strongest ideas learned from the Repo2Eval repositories" \
  --spec "Must be a standalone app unrelated to CAM runtime" \
  --spec "Must use real code and real file changes" \
  --check "pytest -q" \
  --max-minutes 20
```

Step 4: validate the result

```bash
cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

Only after validation passes should you benchmark:

```bash
cam benchmark --max-minutes 5
```

### Real Example B: Use `Repo2Eval` To Improve CAM Itself

Step 1: mine the repos with CAM as the target

```bash
cam mine /Volumes/WS4TB/Repo2Eval \
  --target /Users/o2satz/multiclaw \
  --max-repos 3 \
  --depth 2 \
  --max-minutes 20
```

That tells CAM:

- study the repos in `Repo2Eval`
- extract useful patterns
- store those findings for CAM's own future use

Step 2: inspect what CAM assimilated

```bash
cam kb insights
cam kb domains
cam kb search "repo repair"
cam kb search "test generation"
cam kb synergies
```

Step 3: export the learned material if another app should consume it

```bash
cam forge-export \
  --out data/cam_knowledge_pack.jsonl \
  --max-methodologies 200 \
  --max-tasks 200 \
  --max-minutes 5
```

## How To Decide Which Path To Use

Use the new-app path when your goal is:

- "build a product"
- "make a standalone tool"
- "create a repo that is not CAM"

Use the CAM-improvement path when your goal is:

- "make CAM smarter"
- "teach CAM patterns from outside repos"
- "improve CAM before asking it to build something later"

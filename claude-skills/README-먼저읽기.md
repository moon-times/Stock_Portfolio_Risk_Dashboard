# 배포본 넣기 — 2분

> **오늘 아침 Part 0에서 다 같이 합니다.** 먼저 온 사람은 미리 하세요.

## 1. 프로젝트 폴더를 만든다

터미널에서 (폴더 이름은 마음대로, **한글·띄어쓰기 금지**):

```
mkdir my-project
cd my-project
```

## 2. 받은 zip 을 이 폴더 안에 푼다

`Day2_배포본.zip` 을 풀면 이렇게 나옵니다.

```
CLAUDE.md
specs/tech-stack.md
claude-skills/          ← 이 폴더 이름만 바꿔야 합니다
```

## 3. ★ 가장 쉬운 방법 — Claude에게 시킨다

폴더를 손으로 옮기지 마세요. `claude` 를 실행하고 **아래를 그대로 붙여넣으세요.**

```
지금 폴더에 claude-skills 라는 폴더가 있어. 그 안의 여섯 개 폴더를
.claude/skills/ 로 옮겨줘. .claude/skills 폴더가 없으면 만들어줘.
다 옮긴 뒤 claude-skills 빈 폴더는 지워줘.
```

**끝나면 이렇게 되어 있어야 합니다.**

```
my-project/
├── CLAUDE.md
├── specs/
│   └── tech-stack.md
└── .claude/
    └── skills/
        ├── grilling/SKILL.md
        ├── grill-me/SKILL.md
        ├── to-spec/SKILL.md
        ├── to-tickets/SKILL.md
        ├── implement/SKILL.md
        └── handoff/SKILL.md
```

> **손으로 옮기고 싶으시면** — **VS Code 로 `my-project` 폴더를 여세요.** `.claude` 가 그냥 보입니다.
> Finder·탐색기에서는 숨김 폴더라 안 보입니다 (Mac `Command + Shift + .`, Windows 「보기 → 숨긴 항목」).

## 4. 확인한다

**Claude Code 를 껐다 켜고** (`Ctrl+C` 두 번 → `claude`), 채팅창에 `/` 만 쳐 보세요.
아래 다섯 개가 **목록에 보이면 끝입니다.**

```
/grill-me      /to-spec      /to-tickets      /implement      /handoff
```

> `grilling` 은 목록에 **안 보이는 게 정상**입니다. `/grill-me` 가 대신 불러줍니다.

## 안 보일 때

| 증상 | 처치 |
|---|---|
| 목록에 없다 | **껐다 켜세요.** (`Ctrl+C` 두 번 → `claude`) |
| 그래도 없다 | 위치를 보세요. `.claude/skills/to-spec/SKILL.md` — **폴더 안에 SKILL.md** 여야 합니다 |
| 폴더가 하나 더 깊다 | `claude-skills/skills/…` 처럼 됐을 수 있습니다. Claude에게 다시 시키세요 |
| 끝까지 안 된다 | **손 드세요.** 혼자 10분 쓰지 마세요 |

---

## 이 여섯 개가 뭔가요

**남이 써놓은 긴 프롬프트입니다.** 그게 전부입니다.

`.claude/skills/to-spec/SKILL.md` 를 **VS Code 로** 한번 열어보세요.
**그냥 한국어로 쓴 지시문**입니다. `/to-spec` 을 치면 그 파일이 통째로 AI에게 배달됩니다.

| 스킬 | 언제 쓰나 |
|---|---|
| `/grill-me` | 내 계획을 AI가 심문하게 한다 |
| `/to-spec` | 지금까지의 대화를 명세 파일로 |
| `/to-tickets` | 명세를 만들 수 있는 크기로 쪼갠다 |
| `/implement` | 티켓 하나를 만든다 |
| `/handoff` | 오늘 한 것을 내일 이어받게 파일로 남긴다 |

> 오늘 오후에 **여러분도 하나 만듭니다.** (검사원 에이전트) 그때 이 파일들을 다시 열어볼 겁니다.

## 출처

Matt Pocock, [`mattpocock/skills`](https://github.com/mattpocock/skills) — **학생용으로 줄이고 한국어로 옮긴 판**입니다.
원본은 38개짜리이고, 집에서 이렇게 깝니다 (**Node.js 가 필요합니다 — Day 3에 시연합니다**).

```
npx skills@latest add mattpocock/skills
```

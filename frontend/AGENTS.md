# frontend/ — Next.js 16 + React 19 + shadcn/ui v4

<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## OVERVIEW
Next.js 16 App Router前端, shadcn/ui v4组件库 (base-nova风格), Tailwind CSS v4, React 19。4个页面: 首页输入研究目标并启动, 任务板看板, Agent状态面板, 产出查看。

## STRUCTURE
```
frontend/src/
├── app/
│   ├── layout.tsx        # RootLayout: 导航栏 (首页/任务板/Agent/产出)
│   ├── page.tsx          # 首页: 输入研究目标 → POST /api/runs → POST .../run_all
│   ├── tasks/page.tsx    # 任务板: 8列看板 (Suspense包裹useSearchParams)
│   ├── agents/page.tsx   # Agent面板: 5张卡片, 能力条, 负载进度条
│   └── outputs/page.tsx  # 产出: run切换器, 报告预览, task/subagent详情
├── components/ui/        # shadcn/ui primitives (5个): badge, button, card, separator, tabs
└── lib/
    ├── api.ts            # API client: fetch封装, API_BASE=http://localhost:8000/api
    ├── types.ts          # TS类型: SkillSet, Agent, Task, Run, Output + 中文label map
    └── utils.ts          # shadcn cn() utility
```

## WHERE TO LOOK
| Feature | File | Key Lines |
|---------|------|-----------|
| 启动课题组 | `app/page.tsx` | L38-47 handleSubmit: createRun → runAll → getRun |
| 任务看板 | `app/tasks/page.tsx` | L29-34 Suspense + TasksContent; L59-87 8列渲染 |
| Agent卡片 | `app/agents/page.tsx` | L41-89 Card循环: 状态badge + 负载条 + 6维能力条 |
| API调用 | `lib/api.ts` | L1 API_BASE; L3-9 fetchApi泛型封装 |
| 中文标签 | `lib/types.ts` | TASK_STATUS_LABELS, AGENT_STATUS_LABELS, RUN_STATUS_LABELS, SKILL_NAMES |

## CONVENTIONS
- `"use client"` 标记所有交互页面 (page.tsx, tasks/page.tsx, agents/page.tsx, outputs/page.tsx)
- `@/` 路径别名 → `./src/*`
- shadcn/ui组件从 `@/components/ui/*` 导入
- 所有shadcn组件使用 @base-ui/react primitives (非Radix)
- 使用 `cn()` utility合并className
- useSearchParams必须包裹在 `<Suspense>` 中

## ANTI-PATTERNS
- 不要使用Radix UI primitives (项目使用@base-ui/react)
- 不要使用 tailwind.config.js (Tailwind v4用CSS-native @theme)
- 不要在page.tsx中硬编码API_BASE (使用lib/api.ts)
- 不要忘记useSearchParams的Suspense包裹

## NOTES
- Next.js 16.2.4 + React 19.2.4 是最新版本组合, API变化大
- Tailwind v4无JS配置文件, 所有配置在 `globals.css` 的 `@theme` 块中
- 前端无测试框架, npm test未配置
- 前端无API代理, 直接fetch localhost:8000 (生产需配置rewrite)

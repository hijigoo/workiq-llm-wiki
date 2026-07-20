# LLM Wiki Pipeline

Teams와 Mail(MCP)에서 **기술·노하우 데이터를 자연어로 추출**해 LLM Wiki용 **Markdown 문서**로 만들고,
사용자가 리뷰·수정 후 커밋하면 이 레포의 `app/wiki/`에 반영되는 파이프라인입니다.

Microsoft Work IQ의 두 MCP 서버(`mcp_TeamsServer`, `mcp_MailTools`)를 실제로 호출하며,
개념적으로 `../samples/mcp-web-sample`(Node.js)을 Python으로 옮기고 위키 생성/리뷰 워크플로를 얹었습니다.

## 흐름

```
자연어 질의 + 날짜 범위
        │
        ▼
 extract  ─ 에이전트(LLM 도구호출) 루프로 Teams/Mail MCP에서 관련 데이터만 취합
        │
        ▼
 generate ─ 취합 자료를 LLM Wiki Markdown(front-matter + 본문)으로 변환
        │
        ▼
 review   ─ 사용자가 웹 UI(또는 노트북)에서 초안 검토·수정
        │
        ▼
 commit   ─ app/wiki/ 에 저장 + git commit (해당 문서 파일만 커밋)
```

## 폴더 구조

```
llmwiki-pipeline/
├─ app/
│  ├─ main.py             # FastAPI: 실행/초안/수정/커밋 엔드포인트
│  ├─ pipeline/           # 공유 패키지 (app + notebook 공용)
│  │  ├─ config.py        # 설정, SOURCES(mail/teams), LLM provider 판별
│  │  ├─ auth.py          # MSAL: device-code(기본)/client-credentials 소스별 토큰
│  │  ├─ mcp_client.py    # Streamable-HTTP MCP 클라이언트 (list/call tools)
│  │  ├─ agent.py         # LLM 도구호출 루프(소스별 네임스페이스 라우팅)
│  │  ├─ extract.py       # 자연어 질의 → 관련 데이터 취합
│  │  ├─ generate.py      # 취합 자료 → 위키 Markdown 생성
│  │  ├─ wiki.py          # app/wiki/ 저장·조회·목록 + git commit
│  │  └─ pipeline.py      # 오케스트레이션(run_pipeline)
│  ├─ static/             # 리뷰/수정/커밋 웹 UI
│  └─ wiki/               # 생성 문서 출력 위치(커밋 대상)
├─ notebook/
│  ├─ 01_setup_mcp.ipynb          # MCP 연결·인증·툴 목록 (먼저 실행)
│  ├─ 02_seed_sample_data.ipynb   # write 도구로 샘플 기술/노하우 전송
│  ├─ 03_fetch_data.ipynb         # MCP 툴 직접 호출로 데이터 조회
│  └─ 04_nl_aggregate_to_md.ipynb # 자연어 취합 → Markdown 생성
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 사전 준비

- **Python 3.10+** (개발/검증은 3.13에서 진행). `mcp` 패키지가 3.10 미만을 지원하지 않습니다.
- **Entra ID(Azure AD) 앱 등록**: Mail/Teams MCP 리소스에 대한 **위임(delegated) 권한**이
  관리자 동의(admin consent)되어 있어야 합니다(`McpServers.Mail.All`, `McpServers.Teams.All`).
  `../samples`의 Node 샘플과 동일한 종류의 등록입니다.
- **LLM**: OpenAI 또는 Azure OpenAI 중 하나.

## 설치

```bash
cd llmwiki-pipeline
python3.13 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env           # 값 채우기 (아래 참조)
```

## 환경 설정 (`.env`)

`.env.example`에 전체 항목과 설명이 있습니다. 핵심:

| 변수 | 설명 |
|------|------|
| `TENANT_ID` | MCP 서버를 소유한 테넌트(디렉터리) ID |
| `CLIENT_ID` | Entra 앱 등록의 Application(client) ID |
| `CLIENT_SECRET` | `AUTH_MODE=client_credentials`일 때만 필요 |
| `MAIL_MCP_SERVER_URL` / `TEAMS_MCP_SERVER_URL` | 각 MCP 서버 URL (기본값은 TENANT_ID로 구성) |
| `AUTH_MODE` | `device_code`(권장) 또는 `client_credentials` |
| `TOKEN_CACHE_PATH` | 로그인 토큰 캐시 경로 (기본 `.token_cache.json`) |
| Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, (`AZURE_OPENAI_API_KEY`) | 엔드포인트+배포 설정 시 사용. 키가 없으면 `DefaultAzureCredential`(예: `az login`)로 키리스 인증 |
| OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL` | 위 Azure 미설정 시 사용 |
| `WIKI_DIR` | 문서 출력 폴더(기본 `app/wiki`) |

### 인증 모드

- **`device_code` (기본·권장)**: Work IQ Mail/Teams MCP는 **위임 스코프**를 사용합니다.
  `notebook/01_setup_mcp.ipynb`(또는 아래 터미널 로그인)에서 **한 번** 브라우저 로그인하면
  토큰이 `.token_cache.json`에 저장되고, 이후 노트북과 **웹앱이 조용히 재사용**합니다.
  (웹 요청 중 대화형 device-code 폴링은 어색하므로, 앱은 캐시된 토큰을 사용합니다.)
- **`client_credentials`**: `CLIENT_SECRET`로 앱 전용 토큰을 발급합니다. 테넌트가 해당 앱에
  **애플리케이션 권한**을 부여한 경우에만 동작합니다(많은 테넌트는 위임만 허용).

## 사용 순서

### 1) 노트북으로 셋업·검증

`.venv` 커널로 `notebook/`의 노트북을 **번호 순서대로** 실행합니다.

1. `01_setup_mcp.ipynb` — 로그인(1회) + MCP 툴 목록 확인 → 토큰 캐시 생성
2. `02_seed_sample_data.ipynb` — 샘플 기술/노하우 메일·Teams 메시지 전송(실데이터 write)
3. `03_fetch_data.ipynb` — MCP 툴을 직접 호출해 데이터 조회
4. `04_nl_aggregate_to_md.ipynb` — 자연어 취합 → Markdown 생성(선택적으로 저장/커밋)

Jupyter 실행:

```bash
source .venv/bin/activate
python -m ipykernel install --user --name llmwiki-pipeline --display-name "Python (llmwiki-pipeline)"
jupyter lab        # 또는 VS Code에서 .venv 커널 선택
```

### 2) 웹앱으로 리뷰·커밋

`01`에서 로그인이 끝나 토큰 캐시가 있으면(또는 `client_credentials` 설정) 실행:

```bash
cd app
uvicorn main:app --reload --port 8000
# 브라우저: http://localhost:8000
```

UI에서: **주제(자연어) + 날짜 범위 + 소스 선택 → 실행 → 초안 검토·수정 → 커밋**.
커밋 시 `app/wiki/{YYYY-MM-DD}-{slug}.md`로 저장되고, **그 파일만** 이 레포에 커밋됩니다.

주요 엔드포인트: `GET /api/status`, `POST /api/run`, `POST /api/commit`,
`GET /api/docs`, `GET /api/docs/{filename}`.

## 데일리 실행(자동화) 안내

기본은 **수동 실행 + 날짜 범위 지정**입니다. 매일 자동 실행하려면 `04` 노트북의 흐름을
스크립트로 감싸 스케줄러에 등록하세요. 예: 매일 09:00에 최근 1일 취합.

```cron
# crontab -e  (venv 파이썬 절대경로 사용)
0 9 * * *  cd /path/to/llmwiki-pipeline && \
  .venv/bin/python -c "import asyncio,sys; sys.path.insert(0,'app'); \
  from pipeline import pipeline, wiki; \
  r=asyncio.run(pipeline.run_pipeline('어제의 기술 노하우 요약')); \
  d=r['doc']; \
  print(wiki.save_and_commit(d['markdown'], d['slug'])) if d else print('no doc:', r)"
```

> 자동 커밋을 원치 않으면 `save_and_commit` 대신 `wiki.save_doc(...)`만 호출해 초안만 남기고,
> 사람이 리뷰 후 커밋하도록 하세요.

## 안전 규칙

- **소스 간 데이터 혼합 금지**: 각 소스는 서로 다른 OAuth 리소스이며, 토큰은 소스별로 발급됩니다.
  에이전트는 소스별로 네임스페이스된 툴만 라우팅합니다(`mail__*`, `teams__*`).
- **날조 금지**: 시스템 프롬프트가 실제 ID/데이터만 사용하고 없으면 명시하도록 지시합니다.
- **비밀정보**: `.env`와 `.token_cache.json`은 gitignore 되어 있습니다. 커밋하지 마세요.

## 참고

- 포팅 원본(읽기 전용): `../samples/{mcp-web-sample, mail-mcp-web-sample, teams-mcp-web-sample}`.
- 앱 런타임 커밋은 최종 사용자에게 귀속되도록 별도 co-author 트레일러를 강제하지 않습니다.

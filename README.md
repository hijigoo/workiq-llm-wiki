# workiq-llm-wiki

Microsoft 365 **Work IQ MCP** 서버(Teams · Mail)에 연결해, 조직에 흩어져 있는
**기술·노하우를 자연어로 추출**하고 **Markdown 위키 문서**로 만들어 검토·커밋하는
파이프라인과 참고용 샘플 앱 모음입니다.

## 구성

| 경로 | 설명 |
|---|---|
| [`llmwiki-pipeline/`](llmwiki-pipeline/) | **메인 프로젝트.** Work IQ MCP(Teams/Mail) → LLM 추출·요약 → 리뷰 가능한 Markdown 위키. FastAPI 웹 앱 + Jupyter 노트북(01~04) 포함. |
| [`samples/mcp-web-sample/`](samples/mcp-web-sample/) | Mail + Teams를 하나로 합친 통합 샘플 웹 앱(자연어 채팅 · 툴 사이드바 · 직접 호출). |
| [`samples/mail-mcp-web-sample/`](samples/mail-mcp-web-sample/) | Work IQ **Mail** MCP(`mcp_MailTools`) 전용 샘플 웹 앱. |
| [`samples/teams-mcp-web-sample/`](samples/teams-mcp-web-sample/) | Work IQ **Teams** MCP(`mcp_TeamsServer`) 전용 샘플 웹 앱. |

## 동작 개요

```
Microsoft 365 (Teams · Mail)
        │  Work IQ MCP 서버
        ▼
   MCP 클라이언트 ──► LLM(추출·요약) ──► Markdown 초안
                                          │  사용자 검토·수정
                                          ▼
                                    app/wiki/ 에 커밋
```

- **인증(2개 ID 분리)**: 데이터 접근은 Microsoft 365 사용자 로그인(Authorization Code + PKCE),
  LLM은 별도 자격(Azure OpenAI keyless `az login` 또는 API 키).
- **소스**: Teams, Mail을 개별 또는 함께 선택.
- **출력**: 사람이 검토한 뒤 커밋되는 Markdown 위키 문서.

## 시작하기

메인 파이프라인부터 보세요:

- 설정: [`llmwiki-pipeline/SETUP.md`](llmwiki-pipeline/SETUP.md) — 테넌트/Entra 앱 등록
- 사용법: [`llmwiki-pipeline/README.md`](llmwiki-pipeline/README.md)
- 아키텍처·시퀀스 다이어그램: [`llmwiki-pipeline/ARCHITECTURE.md`](llmwiki-pipeline/ARCHITECTURE.md)

> 자격 증명은 커밋되지 않습니다. `.env`, `.token_cache.json`, `.venv/`,
> 실제 추출 결과(`notebook/wiki/`)는 `.gitignore`로 제외됩니다.

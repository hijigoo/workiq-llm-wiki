---
title: "Kubernetes 파드 CrashLoopBackOff 원인 추적법"
generated: "2026-07-22T01:50:20+00:00"
sources: ["Mail", "Teams"]
date_range: "2026-07-08..2026-07-22"
query: "k8s"
generator: "llmwiki-pipeline"
---

# Kubernetes 파드 CrashLoopBackOff 원인 추적법

## 개요

`CrashLoopBackOff`는 컨테이너가 반복적으로 비정상 종료되어 Kubernetes가 재시작을 시도하는 상태를 의미한다.  
수집된 자료에서는 원인 파악을 위한 최소 조사 절차와 대표적인 대응 포인트를 정리하고 있다.

## 기본 조사 절차

### 1. 파드 이벤트 확인

우선 파드 상태와 이벤트를 확인해 재시작 원인 단서를 수집한다.

```bash
kubectl describe pod
```

확인 포인트:
- 최근 이벤트 메시지
- 재시작 횟수
- 프로브 실패 여부
- 종료 사유 표시 여부

### 2. 직전 컨테이너 로그 확인

재시작 직전 로그를 확인해 애플리케이션 종료 원인을 파악한다.

```bash
kubectl logs --previous
```

현재 컨테이너가 이미 재시작된 상태라면, 직전 실행 인스턴스의 로그가 원인 분석에 유용하다.

## 대표 원인과 대응

### OOMKilled

종료 사유가 `OOMKilled`인 경우, 메모리 부족으로 컨테이너가 종료된 상황이다.

대응 방향:
- 컨테이너의 `requests/limits` 설정 재검토
- 실제 사용량 대비 메모리 할당 상향 여부 검토

관련 키워드:
- `OOMKilled`
- `requests/limits`

### readinessProbe 타임아웃

`readinessProbe` 실패가 잦고 타임아웃 또는 초기 기동 지연이 원인으로 보이는 경우, 프로브 시작 시점을 늦추는 방안을 검토한다.

대응 방향:
- `initialDelaySeconds` 값을 상향 조정

관련 키워드:
- `readinessProbe`
- `initialDelaySeconds`

## 주의사항

- 본 문서는 수집된 메일의 간단한 기술 메모를 기반으로 작성되었으며, 상세한 진단 분기나 예시는 포함되어 있지 않다.
- 명령어 예시에는 파드명, 네임스페이스 등 구체 인자가 제공되지 않았다.
- Teams에서는 관련 기술 자료가 확인되지 않았다.

## 출처

- Mail, MOD Administrator, 2026-07-20, `AAMkAGVkZmNmZDJhLTA3ZDMtNGMzNy1iYzQ0LTdjOTk5OTdiZWIzNgBGAAAAAAASWcWRX9tPRYGpPWTqosoaBwAeZjLIEF47QKXdFJfmI1WyAAAAAAEMAAAeZjLIEF47QKXdFJfmI1WyAAAlFA4xAAA=`

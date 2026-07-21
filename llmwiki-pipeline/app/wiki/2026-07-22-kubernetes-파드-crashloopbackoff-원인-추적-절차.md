---
title: "Kubernetes 파드 CrashLoopBackOff 원인 추적 절차"
generated: "2026-07-21T15:32:18+00:00"
sources: ["Work IQ"]
date_range: "2026-07-14..2026-07-21"
query: "k8s 내용"
generator: "llmwiki-pipeline"
---

# Kubernetes 파드 CrashLoopBackOff 원인 추적 절차

## 개요

Kubernetes 파드가 `CrashLoopBackOff` 상태일 때 확인할 기본 추적 절차를 정리한다.  
수집된 원본 기준으로, 운영 중 재사용 가능한 최소 체크리스트만 포함했다.

## 기본 확인 절차

### 1. Pod 이벤트 확인

우선 파드의 이벤트를 확인해 종료 및 재시작 원인을 파악한다.

```text
kubectl describe pod
```

확인 포인트:
- 컨테이너 종료 사유
- 재시작 반복 여부
- probe 실패 이벤트 존재 여부
- 스케줄링/이미지 풀링 등 부가 오류

### 2. 이전 컨테이너 로그 확인

직전 실패 원인을 확인하기 위해 이전 컨테이너 로그를 조회한다.

```text
kubectl logs --previous
```

확인 포인트:
- 애플리케이션 시작 직후 예외 발생 여부
- 설정 오류, 의존성 연결 실패, 포트 바인딩 실패
- 종료 직전 에러 메시지

## 주요 원인별 대응

### OOMKilled 발생 시

종료 원인이 `OOMKilled`인 경우 리소스 설정을 재검토한다.

```text
OOMKilled면 requests/limits 재조정.
```

대응 방향:
- 메모리 `requests/limits` 상향 또는 적정값으로 재조정
- 애플리케이션 메모리 사용량 점검
- 불필요한 메모리 사용 패턴 확인

### readinessProbe 타임아웃 반복 시

`readinessProbe` 타임아웃이 잦으면 초기 기동 시간이 부족한 경우를 의심한다.

```text
readinessProbe 타임아웃이 잦으면 initialDelaySeconds 상향.
```

대응 방향:
- `initialDelaySeconds` 값을 상향
- 애플리케이션 실제 기동 시간 측정 후 probe 설정 조정
- 필요 시 timeout/period 설정도 함께 검토

## 운영 체크리스트

- `kubectl describe pod`로 이벤트와 종료 사유 확인
- `kubectl logs --previous`로 직전 실패 로그 확인
- `OOMKilled` 여부 확인 후 리소스 재조정
- `readinessProbe` 타임아웃 반복 시 `initialDelaySeconds` 상향 검토

## 한계

원본 자료에는 다음 정보가 포함되어 있지 않다.
- 네임스페이스, 파드명까지 포함한 실제 명령 예시
- `livenessProbe` 관련 대응
- CPU 부족, 이미지 오류, 설정 누락 등 다른 CrashLoopBackOff 원인별 상세 절차

## 출처

- Mail, MOD Administrator, 2026-07-20 07:44, `turn1search3`

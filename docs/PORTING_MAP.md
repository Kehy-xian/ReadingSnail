# 전작(BookEater)에서 가져올 것과 버릴 것

참조: https://github.com/Kehy-xian/BookEater — 브랜치 `release-v0.1.0-beta.4`
(main 브랜치는 거의 비어 있다. 소스는 release-* 브랜치에 있다.)

**전작 저장소는 읽기만 한다. 커밋하지 않는다.**

## 가져온다 — 거의 그대로

| 전작 경로 | 용도 |
|---|---|
| `storage/sqlite_store.py`, `journal.py`, `draft.py`, `settings.py` | 책 1:N 기록, 임시저장 |
| ~~`services/memory.py`~~ | **완료.** `services/recall.py` — 무작위 대신 임베딩 최근접으로 |
| `services/data_transfer.py`, `version_backup.py` | 백업·이전·버전 전환 |
| ~~`pet_sprite.py`, `pet_art.py`, `sprite_validation.py`~~ | **완료.** `pet/art.py`·`sprites.py`·`validation.py`. 진화 형태·승인 계보는 버림 |
| ~~`tools/validate_sprite_pack.py`, `install_sprite_override.py`~~ | **완료.** + `render_placeholder_pack.py` 추가 |
| ~~`pet_behavior.py`~~ | **완료.** `pet/behavior.py` — 8방향·수직 절반 속도로 고쳐 가져옴 |
| `services/single_instance.py`, `windows_autostart.py`, `update_check.py`, `update_install.py` | 운영 인프라 |
| `BookEater.spec`, `installer/BookEater.iss` | 빌드·설치 (모델 경로만 수정) |

## 가져오되 고친다

| 전작 | 변경 |
|---|---|
| ~~`pet_window.py` + `pet_window_v2`~`v11`~~ | **완료.** 11단계 3,469줄 → `pet/window.py` 단일 클래스 |
| ~~`services/dialogue.py`~~ | **완료.** 4갈래 가중치 + `services/speaker.py` 로 저장소 연결 |
| ~~`services/catalog.py`~~ | **완료.** `services/catalog/` 어댑터 3종. Worker 를 쓰려면 `searchBooks()` 만 국중으로 바꾸면 계약은 그대로다 |
| ~~`ci/e5_targeted_validation.py`의 `E5`~~ | **완료.** `nlp/encoder.py` — 인코더만. 성향 분류는 안 가져옴 |

## 버린다

| 전작 | 줄 수 |
|---|---:|
| `game/` 전체 (진화·영양·성장노선·도감·미니게임) | 1,375 |
| `nlp/hybrid_classifier*.py` 3종 (분류·임계값·캘리브레이션) | 381 |
| `storage/care.py`, `encyclopedia.py`, `milestones.py` | ~400 |
| `ci/growth_*`, `ci/e5_*` 검증 스크립트 | ~2,300 |
| `tests/` 중 growth·evolution·monster·care·play 계열 15개 내외 | ~1,500 |
| `tools/generate_*_sprites.py` (진화형 스프라이트 생성기) | ~700 |
| Cloudflare `improvement_examples` (기록 서버 전송) | — |
| 진화형 스프라이트 9종 (`pagedge`~`route_c2`) | — |

## 용량에 대한 주의

설치본 239MB의 대부분은 **번들된 multilingual-e5-small ONNX 모델**이다.
위 코드를 전부 지워도 용량은 거의 그대로다.

의미 검색을 유지하기로 했으므로 모델은 남는다. 대신 **INT8 양자화**로 줄인다.
전작 `tools/fetch_e5_model.py` 주석에 이미 계획으로 적혀 있다.
목표: 설치본 60~80MB대.

양자화 후에는 반드시 검증할 것. 전작 `ci/e5_targeted_validation.py`가
두 백엔드를 나란히 비교하는 구조라 INT8을 세 번째로 추가하면 그대로 쓸 수 있다.

## 데이터 마이그레이션

전작 beta.4 사용자가 있다면 `monster_state`는 버리고
`reading_entries`와 책 목록은 살려야 한다. 1단계에 포함할 것.

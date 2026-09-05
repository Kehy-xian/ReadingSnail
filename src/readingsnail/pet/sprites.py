"""스프라이트 적재·합성·캐시.

전작에서 가져온 태도 (pet_sprite.py)
    · **한 상태는 한 출처에서 통째로.** 프레임을 출처끼리 섞지 않는다.
    · 사용자 교체본이 우선이되, **깨진 교체본이 멀쩡한 번들 그림을 가리지 않는다.**
      교체본 적재에 실패하면 번들로 내려간다.
    · Tk PhotoImage 는 파이썬 참조가 사라지면 회수된다. 캐시가 참조를 붙들고 있다.

전작에서 버린 것
    진화 형태(form_id)·승인 계보·상속. 달팽이는 하나다.

없어도 돌아간다
    Pillow 가 없거나 그림이 없으면 frames() 가 None 을 돌려주고, 창은 벡터로
    그린다(CLAUDE.md '무너져도 기록에는 닿아야 한다').
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import art

SPRITES_RELATIVE = Path('resources') / 'sprites'
PROPS_RELATIVE = Path('resources') / 'props'
OVERRIDE_DIRNAME = 'art_overrides'

# 원본 한 변의 상한. 규격은 190 이지만 2배·4배로 그려 온 원화를 받아주려고 여유를 둔다.
# 상한이 없으면 6000x6000 짜리 한 장이 144MB 로 펼쳐지고, 프레임 8장이면 1GB 를 넘는다.
# 잘못 만든 팩 하나가 앱을 메모리로 눌러버리는 길을 막는다.
MAX_SOURCE_SIDE = art.CANVAS * 4


def bundled_sprite_root(resource_root: str | Path) -> Path:
    return Path(resource_root) / SPRITES_RELATIVE


def bundled_prop_root(resource_root: str | Path) -> Path:
    return Path(resource_root) / PROPS_RELATIVE


def override_root(data_dir: str | Path) -> Path:
    """사용자가 자기 그림을 넣는 곳. 설치본을 건드리지 않는다."""
    return Path(data_dir) / OVERRIDE_DIRNAME


def pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


# ── 합성 ──────────────────────────────────────────────
def compose_frame(root: str | Path, state: str, index: int, *,
                  slug: str = art.SLUG, props: tuple[str, ...] = (),
                  prop_root: str | Path | None = None):
    """한 프레임을 만들어 PIL 이미지로 돌려준다.

    쌓는 순서: 몸통 → 껍데기 → 소품. 껍데기가 고정 레이어면 프레임마다 다시
    그리지 않아도 되고, 소품도 프레임 재작업 없이 위에 얹힌다.
    """
    from PIL import Image

    def _open(path):
        image = Image.open(path)
        if max(image.size) > MAX_SOURCE_SIDE:
            size = image.size
            image.close()
            raise ValueError(
                f'그림이 너무 크다 {size[0]}x{size[1]} (한 변 {MAX_SOURCE_SIDE}px 이하): {path.name}')
        return image

    folder = Path(root)
    if art.has_full_animation(folder, state, slug=slug):
        with _open(art.frame_paths(folder, state, slug=slug)[index]) as base:
            canvas = base.convert('RGBA')
    elif art.has_layered_animation(folder, state, slug=slug):
        body_path = art.frame_paths(folder, state, slug=slug, body_only=True)[index]
        with _open(body_path) as body:
            canvas = body.convert('RGBA')
        with _open(art.shell_path(folder, slug=slug)) as shell:
            shell_layer = shell.convert('RGBA')
        if shell_layer.size != canvas.size:
            shell_layer = shell_layer.resize(canvas.size)
        canvas.alpha_composite(shell_layer)
    else:
        raise FileNotFoundError(f'{state} 프레임이 온전하지 않다: {folder}')

    if props:
        source = Path(prop_root) if prop_root is not None else folder
        for name in props:
            try:
                path = art.prop_path(source, name)
            except ValueError:
                # 소품 이름은 설정에서 온다. 규칙에 안 맞는다고 그리기가 터지면
                # 설정 한 줄이 달팽이를 안 보이게 만든다.
                continue
            if not path.is_file():
                continue        # 없는 소품은 그리지 않는다. 그것뿐이다.
            try:
                with _open(path) as overlay:
                    layer = overlay.convert('RGBA')
            except (ValueError, OSError):
                continue        # 소품 한 장 때문에 달팽이가 안 보이면 안 된다
            if layer.size != canvas.size:
                layer = layer.resize(canvas.size)
            canvas.alpha_composite(layer)
    return canvas


def _prepare(image, *, facing: int, size: int):
    """좌우 반전과 크기 조정. 원화는 좌향만 그린다(SPRITE_GUIDE_KO.md)."""
    from PIL import Image

    if facing > 0:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


class SpriteCache:
    """상태별 Tk 이미지. 참조를 붙들고 있어야 Tk 가 회수하지 않는다."""

    def __init__(self, tk_module: Any, resource_root: str | Path, *,
                 master: Any = None, data_dir: str | Path | None = None,
                 slug: str = art.SLUG):
        # **master 는 이 캐시가 붙을 Tk 창이다.** ImageTk.PhotoImage 는 넘기지 않으면
        # 기본 root 에 만들어지고, 다른 창의 캔버스에 쓰면
        # 'image "pyimageN" doesn't exist' 로 터진다. 폰트 캐시와 같은 함정이다.
        # 창마다 캐시를 하나씩 두고, 창을 새로 만들면 캐시도 새로 만든다.
        self.tk = tk_module
        self.master = master
        self.resource_root = Path(resource_root)
        self.bundled = bundled_sprite_root(resource_root)
        self.overrides = override_root(data_dir) if data_dir is not None else None
        self.prop_root = bundled_prop_root(resource_root)
        self.slug = slug
        self.props: tuple[str, ...] = ()
        self._cache: dict[tuple[str, int, int], tuple[Any, ...] | None] = {}

    # ── 출처 ──────────────────────────────────────────
    def sources(self) -> tuple[Path, ...]:
        """교체본 먼저, 그다음 번들."""
        roots = []
        if self.overrides is not None and self.overrides.is_dir():
            roots.append(self.overrides)
        roots.append(self.bundled)
        return tuple(roots)

    def available_states(self) -> tuple[str, ...]:
        seen: list[str] = []
        for root in self.sources():
            for state in art.available_states(root, slug=self.slug):
                if state not in seen:
                    seen.append(state)
        return tuple(seen)

    def set_props(self, props: tuple[str, ...]) -> None:
        """소품을 갈아끼운다. 순수 사용자 선택이다 — 해금 개념이 없다."""
        if tuple(props) == self.props:
            return
        self.props = tuple(props)
        self._cache.clear()

    def available_props(self) -> tuple[str, ...]:
        found: list[str] = []
        for root in ((self.overrides,) if self.overrides else ()) + (self.prop_root,):
            if root is None:
                continue
            for name in art.list_props(root):
                if name not in found:
                    found.append(name)
        return tuple(found)

    # ── 적재 ──────────────────────────────────────────
    def _load(self, root: Path, state: str, *, facing: int, size: int):
        from PIL import ImageTk

        count = art.ANIMATIONS[state].frames
        images = []
        for index in range(count):
            frame = compose_frame(root, state, index, slug=self.slug,
                                  props=self.props, prop_root=self.prop_root)
            images.append(ImageTk.PhotoImage(
                _prepare(frame, facing=facing, size=size), master=self.master))
        return tuple(images)

    def frames(self, state: str, *, facing: int = -1,
               size: int = art.CANVAS) -> tuple[Any, ...] | None:
        """그 상태의 Tk 이미지들. 그림이 없으면 None — 창이 벡터로 그린다."""
        if state not in art.ANIMATIONS or not pillow_available():
            return None
        key = (state, 1 if facing > 0 else -1, int(size))
        if key in self._cache:
            return self._cache[key]

        for root in self.sources():
            if not (art.has_full_animation(root, state, slug=self.slug)
                    or art.has_layered_animation(root, state, slug=self.slug)):
                continue
            try:
                images = self._load(root, state, facing=facing, size=size)
            except Exception:
                # 깨진 교체본이 멀쩡한 번들 그림을 가리지 않는다. 다음 출처로.
                continue
            self._cache[key] = images
            return images

        self._cache[key] = None
        return None

    def invalidate(self) -> None:
        """들고 있던 Tk 이미지를 놓아준다.

        **창을 부수기 전에 부를 것.** ImageTk.PhotoImage 는 회수될 때 자기
        인터프리터에 'image delete' 를 보내는데, 인터프리터가 먼저 사라지면
        그 소멸자가 프로세스를 죽인다.
        """
        self._cache.clear()


def frame_index(state: str, elapsed_ms: int) -> int:
    """흐른 시간으로 몇 번째 장인지. 반복하지 않는 상태는 마지막 장에서 멈춘다."""
    spec = art.ANIMATIONS.get(state)
    if spec is None:
        return 0
    step = max(0, int(elapsed_ms)) // spec.frame_ms
    if spec.loop:
        return step % spec.frames
    return min(step, spec.frames - 1)

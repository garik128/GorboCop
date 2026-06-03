"""Детекция позы по вебкамере через MediaPipe Face Detection.

Отслеживаем размер bounding box лица (близость к камере) и Y-координату центра
лица (наклон вниз). Сравниваем с baseline, полученным при калибровке.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto

import cv2
import mediapipe as mp

# Минимум кадров с лицом, чтобы калибровка считалась успешной.
MIN_CALIB_SAMPLES = 15
# Разброс координат рамки (доля кадра), ниже которого объект считается
# неподвижным: реальное лицо за минуты всегда смещается сильнее.
STATIC_RANGE_EPS = 0.012
# Сколько подряд неудачных чтений камеры терпим до попытки переоткрыть её.
MAX_READ_FAILURES = 90


class PostureState(Enum):
    NO_FACE = auto()      # лицо не найдено
    CALIBRATING = auto()  # идёт калибровка
    GOOD = auto()         # поза в норме
    BAD = auto()          # наклонился к клавиатуре


@dataclass
class FaceMetrics:
    """Метрики лица в текущем кадре (относительные координаты 0..1)."""
    box_height: float
    center_y: float


@dataclass
class DetectionResult:
    state: PostureState
    # Кадр BGR с нанесённой разметкой (для превью). Может быть None.
    frame: object = None
    # Прогресс калибровки 0..1.
    calibration_progress: float = 0.0
    # Отношение текущего размера лица к baseline и смещение Y (для отладки/статуса).
    size_ratio: float = 1.0
    y_delta: float = 0.0
    # Какой признак сработал.
    approach: bool = False  # лицо приблизилось (выросло)
    tilt: bool = False      # лицо опустилось вниз
    # Найденный объект неподвижен слишком долго — считаем, что это не лицо.
    static_scene: bool = False
    # Камера не отдаёт кадры (нет устройства или чтение сломалось).
    camera_error: bool = False


class PostureDetector:
    """Захват кадров и анализ позы.

    Не запускает потоков сам — вызывающий код дёргает process_frame() в цикле.
    """

    def __init__(self, config):
        self.config = config
        self._cap: cv2.VideoCapture | None = None
        self._face = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=config.min_detection_confidence,
        )

        # baseline после калибровки; при старте подхватываем сохранённый,
        # чтобы не калиброваться заново после перезапуска приложения.
        self._baseline_height: float | None = config.baseline_height
        self._baseline_y: float | None = config.baseline_y

        # состояние калибровки
        self._calibrating = False
        self._calib_start = 0.0
        self._calib_samples: list[FaceMetrics] = []
        # Момент последней неудачной калибровки (мало кадров с лицом).
        self.calibration_failed_at: float | None = None

        # Отложенная смена порога уверенности: применяется в process_frame,
        # чтобы не пересоздавать FaceDetection из чужого потока.
        self._pending_confidence: float | None = None

        # Трек рамки лица для отсечения неподвижных объектов (подголовник):
        # сэмплы (t, center_x, center_y, height), примерно раз в секунду.
        self._track: deque[tuple[float, float, float, float]] = deque()
        self._last_track_t = 0.0

        self._read_failures = 0

    # ---- управление камерой -------------------------------------------------
    def open_camera(self) -> bool:
        if self._cap is not None and self._cap.isOpened():
            return True
        # CAP_DSHOW даёт быстрый старт камеры на Windows.
        cap = cv2.VideoCapture(self.config.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.config.camera_index)
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap = cap
        return True

    def release_camera(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def is_calibrated(self) -> bool:
        return self._baseline_height is not None and self._baseline_y is not None

    def apply_config_baseline(self) -> None:
        """Перечитать baseline из конфига (после сброса настроек)."""
        self._baseline_height = self.config.baseline_height
        self._baseline_y = self.config.baseline_y

    def request_confidence(self, value: float) -> None:
        """Попросить сменить порог уверенности; применится в потоке детекции."""
        self._pending_confidence = float(value)

    # ---- калибровка ---------------------------------------------------------
    def start_calibration(self) -> None:
        self._calibrating = True
        self._calib_start = time.time()
        self._calib_samples = []
        self.calibration_failed_at = None

    def _finish_calibration(self) -> None:
        self._calibrating = False
        if len(self._calib_samples) >= MIN_CALIB_SAMPLES:
            n = len(self._calib_samples)
            self._baseline_height = sum(s.box_height for s in self._calib_samples) / n
            self._baseline_y = sum(s.center_y for s in self._calib_samples) / n
            # Сохраняем baseline, чтобы пережить перезапуск приложения.
            self.config.baseline_height = self._baseline_height
            self.config.baseline_y = self._baseline_y
            self.config.save()
            self.calibration_failed_at = None
        else:
            # Лицо почти не было видно — baseline не трогаем.
            self.calibration_failed_at = time.time()

    # ---- отсечение неподвижных объектов -------------------------------------
    def _is_static_scene(self, box, metrics: FaceMetrics) -> bool:
        """True, если рамка «лица» практически не двигалась всё окно наблюдения.

        Реальная голова даже у спокойно сидящего человека за минуты смещается
        заметно сильнее сенсорного шума; мебель — нет.
        """
        window = float(self.config.static_scene_minutes or 0.0) * 60.0
        if window <= 0:
            return False
        now = time.time()
        if now - self._last_track_t >= 1.0:
            cx = box.xmin + box.width / 2.0
            self._track.append((now, cx, metrics.center_y, metrics.box_height))
            self._last_track_t = now
        while self._track and now - self._track[0][0] > window:
            self._track.popleft()
        # Судим только когда наблюдений хватает на почти всё окно.
        if len(self._track) < 10 or now - self._track[0][0] < window * 0.9:
            return False
        xs = [s[1] for s in self._track]
        ys = [s[2] for s in self._track]
        hs = [s[3] for s in self._track]
        spread = max(
            max(xs) - min(xs), max(ys) - min(ys), max(hs) - min(hs)
        )
        return spread < STATIC_RANGE_EPS

    # ---- разбор кадра -------------------------------------------------------
    def _best_box(self, detections):
        """Относительный bbox самого крупного (ближайшего) лица или None."""
        if not detections:
            return None
        best = max(
            detections,
            key=lambda d: d.location_data.relative_bounding_box.height,
        )
        return best.location_data.relative_bounding_box

    def _draw(self, frame, box, state: PostureState):
        h, w = frame.shape[:2]
        color = {
            PostureState.GOOD: (0, 200, 0),
            PostureState.BAD: (0, 0, 255),
            PostureState.CALIBRATING: (0, 200, 200),
            PostureState.NO_FACE: (120, 120, 120),
        }[state]
        if box is not None:
            x1 = int(box.xmin * w)
            y1 = int(box.ymin * h)
            x2 = int((box.xmin + box.width) * w)
            y2 = int((box.ymin + box.height) * h)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        # Рамка по периметру кадра как индикатор состояния.
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), color, 3)
        return frame

    def process_frame(self) -> DetectionResult:
        if self._pending_confidence is not None:
            conf = self._pending_confidence
            self._pending_confidence = None
            try:
                self._face.close()
            except Exception:
                pass
            self._face = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=conf
            )

        if self._cap is None or not self._cap.isOpened():
            return DetectionResult(state=PostureState.NO_FACE, camera_error=True)

        ok, frame = self._cap.read()
        if not ok or frame is None:
            # Камера отвалилась (занята/отключена) — периодически пробуем
            # переоткрыть, не требуя ручного стоп/старт.
            self._read_failures += 1
            if self._read_failures >= MAX_READ_FAILURES:
                self._read_failures = 0
                self.release_camera()
                self.open_camera()
            return DetectionResult(state=PostureState.NO_FACE, camera_error=True)
        self._read_failures = 0

        frame = cv2.flip(frame, 1)  # зеркало, как привычно пользователю
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._face.process(rgb)

        box = self._best_box(results.detections)
        metrics = None
        if box is not None:
            metrics = FaceMetrics(
                box_height=box.height, center_y=box.ymin + box.height / 2.0
            )

        # Калибровка.
        if self._calibrating:
            if metrics is not None:
                self._calib_samples.append(metrics)
            elapsed = time.time() - self._calib_start
            progress = min(elapsed / self.config.calibration_seconds, 1.0)
            if progress >= 1.0:
                self._finish_calibration()
            state = PostureState.CALIBRATING
            self._draw(frame, box, state)
            return DetectionResult(
                state=state, frame=frame, calibration_progress=progress
            )

        # Нет лица.
        if metrics is None:
            state = PostureState.NO_FACE
            self._draw(frame, box, state)
            return DetectionResult(state=state, frame=frame)

        # Объект не двигался всё окно наблюдения — это мебель (подголовник),
        # а не лицо: не алертим и показываем как «нет лица».
        if self._is_static_scene(box, metrics):
            state = PostureState.NO_FACE
            self._draw(frame, box, state)
            return DetectionResult(state=state, frame=frame, static_scene=True)

        # Без baseline считаем позу хорошей (мониторинг ждёт калибровки).
        if not self.is_calibrated:
            self._draw(frame, box, PostureState.GOOD)
            return DetectionResult(state=PostureState.GOOD, frame=frame)

        size_ratio = metrics.box_height / self._baseline_height
        y_delta = metrics.center_y - self._baseline_y

        # Любой признак наклона к клавиатуре считаем плохой позой: лицо либо
        # приблизилось (выросло), либо опустилось вниз. При наклоне головы вниз
        # bbox может не расти, поэтому одного условия по размеру недостаточно.
        approach = size_ratio >= self.config.size_threshold
        tilt = y_delta >= self.config.y_drop_threshold
        state = PostureState.BAD if (approach or tilt) else PostureState.GOOD
        self._draw(frame, box, state)
        return DetectionResult(
            state=state, frame=frame, size_ratio=size_ratio, y_delta=y_delta,
            approach=approach, tilt=tilt,
        )

    def close(self) -> None:
        self.release_camera()
        self._face.close()

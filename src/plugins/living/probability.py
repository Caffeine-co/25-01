import math
from src.plugins.living.config import active_model
from src.plugins.living.utils import ts_to_time


def ts_to_hour_and_weekday(timestamp: int) -> tuple[float, str]:
    dt = ts_to_time(timestamp)
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    weekday = str(dt.weekday())
    return hour, weekday

def weekday_enabled(weekday: str, weekdays: list[int|str]|None) -> bool:
    if weekdays is None:
        return True
    return weekday in {str(day) for day in weekdays}

def circular_hour_distance(current_hour: float, center_hour: float) -> float:
    direct_distance = abs(current_hour - center_hour)
    return min(direct_distance, 24.0 - direct_distance)

def gaussian_time_peak(current_hour: float, center_hour: float, width_hour: float) -> float:
    if width_hour <= 0:
        raise ValueError("width_hour 必须大于 0")
    distance = circular_hour_distance(
        current_hour=current_hour,
        center_hour=center_hour
    )
    normalized_distance = (distance / width_hour)
    return math.exp(-0.5 * normalized_distance * normalized_distance)

def sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)

def smooth_time_window_weight(current_hour: float, start_hour: float, end_hour: float, steepness: float) -> float:
    if steepness <= 0:
        raise ValueError("edge_steepness 必须大于 0")
    duration = (end_hour - start_hour) % 24.0
    if duration == 0:
        return 1.0
    unwrapped_end = start_hour + duration
    def window_weight(hour: float) -> float:
        enter_transition = sigmoid(steepness * (hour - start_hour))
        leave_transition = sigmoid(steepness * (unwrapped_end - hour))
        return enter_transition * leave_transition
    return max(
        window_weight(current_hour - 24.0),
        window_weight(current_hour),
        window_weight(current_hour + 24.0)
    )

def awake_weight(current_hour: float) -> float:
    wake_hour = active_model["wake_hour"]
    sleep_hour = active_model["sleep_hour"]
    steepness = active_model["awake_edge_steepness"]
    sleep_floor = active_model["sleep_floor"]
    raw_awake_weight = smooth_time_window_weight(
        current_hour=current_hour,
        start_hour=wake_hour,
        end_hour=sleep_hour,
        steepness=steepness
    )
    return sleep_floor + (1.0 - sleep_floor) * raw_awake_weight

# def calculate_peak_rate(current_hour: float) -> float:
def calculate_peak_rate(current_hour: float, weekday: str) -> float:
    total_peak_rate = 0.0
    activity_peaks = active_model["activity_peaks"]
    for peak in activity_peaks:
        if not weekday_enabled(weekday, peak.get("weekdays")):
            continue
        peak_weight = gaussian_time_peak(
            current_hour=current_hour,
            center_hour=peak["center_hour"],
            width_hour=peak["width_hour"]
        )
        total_peak_rate += peak["rate_per_hour"] * peak_weight
    return total_peak_rate

def calculate_availability_multiplier(current_hour: float, weekday: str) -> float:
    multiplier = 1.0
    for window in active_model.get("availability_windows", []):
        if not weekday_enabled(weekday, window.get("weekdays")):
            continue
        target_multiplier = window["multiplier"]
        if target_multiplier < 0:
            raise ValueError("availability window multiplier 不得小于 0")
        weight = smooth_time_window_weight(
            current_hour=current_hour,
            start_hour=window["start_hour"],
            end_hour=window["end_hour"],
            steepness=window.get("edge_steepness", 4.0)
        )
        multiplier *= 1.0 + (target_multiplier - 1.0) * weight
    return multiplier

def calculate_open_rate(timestamp: int) -> float:
    current_hour, weekday = ts_to_hour_and_weekday(timestamp)
    base_rate = active_model["base_rate_per_hour"]
    peak_rate = calculate_peak_rate(
        current_hour=current_hour,
        weekday=weekday
    )
    current_awake_weight = awake_weight(
        current_hour=current_hour
    )
    availability_multiplier = (
        calculate_availability_multiplier(
            current_hour=current_hour,
            weekday=weekday
        )
    )
    weekday_multipliers = active_model["weekday_multipliers"]
    weekday_multiplier = weekday_multipliers.get(weekday, 1.0)
    global_multiplier = active_model["global_rate_multiplier"]
    rate_per_hour = (
        global_multiplier
        * weekday_multiplier
        * current_awake_weight
        * availability_multiplier
        * (base_rate + peak_rate)
    )
    return max(0.0, rate_per_hour)

def rate_to_probability(rate_per_hour: float, interval_seconds: int) -> float:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds 必须大于 0")
    interval_hours = (interval_seconds / 3600.0)
    return 1.0 - math.exp(-rate_per_hour * interval_hours)

def active_probability(timestamp: int) -> float:
    rate_per_hour = calculate_open_rate(timestamp=timestamp)
    interval_seconds = active_model["poll_interval_seconds"]
    probability = rate_to_probability(
        rate_per_hour=rate_per_hour,
        interval_seconds=interval_seconds
    )
    return max(probability, 0.0)
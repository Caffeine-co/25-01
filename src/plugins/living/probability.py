import math
from datetime import datetime, timedelta, timezone
from src.plugins.living.config import setting_cfg
from src.plugins.living.utils import ts_to_time


active_model_args = setting_cfg["active_model_args"]

def ts_to_hour_and_weekday(timestamp: int) -> tuple[float, str]:
    local_tz = timezone(timedelta(hours=setting_cfg["tz_offset"]))
    local_datetime = datetime.fromtimestamp(timestamp, tz=local_tz)
    _local_datetime = ts_to_time(timestamp)
    hour = (
        local_datetime.hour
        + local_datetime.minute / 60.0
        + local_datetime.second / 3600.0
    )
    weekday = str(local_datetime.weekday())
    return hour, weekday

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

def awake_weight(current_hour: float,) -> float:
    wake_hour = active_model_args["wake_hour"]
    sleep_hour = active_model_args["sleep_hour"]
    steepness = active_model_args["awake_edge_steepness"]
    sleep_floor = active_model_args["sleep_floor"]
    hours_after_wake = (current_hour - wake_hour) % 24.0
    awake_duration = (sleep_hour - wake_hour) % 24.0
    if awake_duration == 0:
        awake_duration = 24.0
    wake_transition = sigmoid(steepness * hours_after_wake)
    sleep_transition = sigmoid(
        steepness
        * (awake_duration - hours_after_wake)
    )
    raw_awake_weight = (
        wake_transition
        * sleep_transition
    )
    return (
        sleep_floor
        + (1.0 - sleep_floor)
        * raw_awake_weight
    )

def calculate_peak_rate(current_hour: float,) -> float:
    total_peak_rate = 0.0
    activity_peaks = active_model_args["activity_peaks"]
    for peak in activity_peaks:
        peak_weight = gaussian_time_peak(
            current_hour=current_hour,
            center_hour=peak["center_hour"],
            width_hour=peak["width_hour"]
        )
        total_peak_rate += (
            peak["rate_per_hour"]
            * peak_weight
        )
    return total_peak_rate

def calculate_open_rate(timestamp: int) -> float:
    current_hour, weekday = ts_to_hour_and_weekday(timestamp)
    base_rate = active_model_args["base_rate_per_hour"]
    peak_rate = calculate_peak_rate(
        current_hour=current_hour
    )
    current_awake_weight = awake_weight(
        current_hour=current_hour
    )
    weekday_multipliers = active_model_args["weekday_multipliers"]
    weekday_multiplier = weekday_multipliers.get(weekday, 1.0)
    global_multiplier = active_model_args["global_rate_multiplier"]
    rate_per_hour = (
        global_multiplier
        * weekday_multiplier
        * current_awake_weight
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
    interval_seconds = active_model_args["poll_interval_seconds"]
    probability = rate_to_probability(
        rate_per_hour=rate_per_hour,
        interval_seconds=interval_seconds
    )
    return max(probability, 0.0)
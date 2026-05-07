"""天气查询工具 - 通过wttr.in API查询天气"""
import requests


def tool_query_weather(city: str, forecast_days: int = 0, language: str = "zh") -> str:
    """查询城市天气
    
    Args:
        city: 城市名称（中文或英文，如"北京"或"Beijing"）
        forecast_days: 预报天数（0=当前，1=明天，2=后天）
        language: 返回语言（zh=中文，en=英文）
    
    Returns:
        天气信息文本
    """
    try:
        # wttr.in API
        url = f"https://wttr.in/{city}"
        params = {
            "format": "j1",  # JSON格式
            "lang": language,
        }
        
        if forecast_days > 0:
            params["num_of_days"] = min(forecast_days, 3)  # 最多3天
        
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # 当前天气
        current = data.get("current_condition", [{}])[0]
        temp_c = current.get("temp_C", "未知")
        feels_like_c = current.get("FeelsLikeC", "未知")
        weather_desc = current.get("weatherDesc", [{}])[0].get("value", "未知")
        humidity = current.get("humidity", "未知")
        wind_speed = current.get("windspeedKmph", "未知")
        wind_dir = current.get("winddir16Point", "未知")
        
        result = f"🌤️ {city} 当前天气\n"
        result += f"━━━━━━━━━━━━━━━━\n"
        result += f"🌡️ 温度: {temp_c}°C（体感 {feels_like_c}°C）\n"
        result += f"☁️ 状况: {weather_desc}\n"
        result += f"💧 湿度: {humidity}%\n"
        result += f"💨 风速: {wind_speed}km/h（{wind_dir}）\n"
        
        # 预报
        if forecast_days > 0:
            for day_data in data.get("weather", [])[:forecast_days]:
                date = day_data.get("date", "")
                avg_temp = day_data.get("avgtempC", "未知")
                max_temp = day_data.get("maxtempC", "未知")
                min_temp = day_data.get("mintempC", "未知")
                
                # 白天天气描述
                day_desc = ""
                if day_data.get("hourly"):
                    day_desc = day_data["hourly"][0].get("lang_zh", [{}])[0].get("value", "")
                    if not day_desc:
                        day_desc = day_data["hourly"][0].get("weatherDesc", [{}])[0].get("value", "")
                
                result += f"\n📅 {date} 预报\n"
                result += f"  🌡️ {min_temp}°C ~ {max_temp}°C（平均 {avg_temp}°C）\n"
                if day_desc:
                    result += f"  ☁️ {day_desc}\n"
        
        return result
        
    except requests.exceptions.Timeout:
        return "❌ 天气查询超时，请稍后重试"
    except requests.exceptions.ConnectionError:
        return "❌ 无法连接到天气服务（wttr.in），请检查网络连接"
    except requests.exceptions.HTTPError as e:
        return f"❌ 天气服务返回错误: {e.response.status_code}"
    except Exception as e:
        return f"❌ 天气查询失败: {type(e).__name__}: {e}"


# 工具定义（供register_builtin_tools使用）
WEATHER_TOOL = {
    "name": "query_weather",
    "description": "查询指定城市的天气信息，支持当前天气和未来3天预报",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称，支持中文（如'北京'）或英文（如'Beijing'）"
            },
            "forecast_days": {
                "type": "integer",
                "description": "预报天数（0=当前天气，1=包含明天，2=包含后天，最多3天）",
                "default": 0
            },
            "language": {
                "type": "string",
                "description": "返回语言（zh=中文，en=英文）",
                "default": "zh"
            }
        },
        "required": ["city"]
    },
    "func": tool_query_weather
}

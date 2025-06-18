import time
import pandas as pd
import numpy as np
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
import requests
from datetime import datetime
import threading
import os
import psutil
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from logging.handlers import RotatingFileHandler

# ======================
# 配置加载器
# ======================
def load_config(config_file='config.json'):
    """加载配置文件（支持带注释的JSON格式）"""
    try:
        # 读取文件并去除注释
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 简单的注释去除（处理行尾注释）
        lines = content.split('\n')
        cleaned_lines = []
        for line in lines:
            # 找到注释位置，但要避免字符串内的//
            in_string = False
            escape_next = False
            comment_pos = -1
            
            for i, char in enumerate(line):
                if escape_next:
                    escape_next = False
                    continue
                    
                if char == '\\':
                    escape_next = True
                    continue
                    
                if char == '"':
                    in_string = not in_string
                    continue
                    
                if not in_string and char == '/' and i + 1 < len(line) and line[i + 1] == '/':
                    comment_pos = i
                    break
            
            # 去除注释部分
            if comment_pos >= 0:
                line = line[:comment_pos].rstrip()
            
            cleaned_lines.append(line)
        
        # 重新组装并解析JSON
        cleaned_content = '\n'.join(cleaned_lines)
        config_data = json.loads(cleaned_content)
        
        # 转换时间间隔字符串为Binance常量
        interval_map = {
            '1m': Client.KLINE_INTERVAL_1MINUTE,
            '3m': Client.KLINE_INTERVAL_3MINUTE,
            '5m': Client.KLINE_INTERVAL_5MINUTE,
            '15m': Client.KLINE_INTERVAL_15MINUTE,
            '30m': Client.KLINE_INTERVAL_30MINUTE,
            '1h': Client.KLINE_INTERVAL_1HOUR,
            '4h': Client.KLINE_INTERVAL_4HOUR,
            '1d': Client.KLINE_INTERVAL_1DAY
        }
        
        # 构建CONFIG字典
        CONFIG = {
            # API配置
            'API_KEY': config_data['api']['api_key'],
            'API_SECRET': config_data['api']['api_secret'],
            'TESTNET': config_data['api']['testnet'],
            'TRADING_TYPE': config_data['api'].get('trading_type', 'spot'),  # 默认现货
            'TELEGRAM_TOKEN': config_data['telegram']['token'],
            'TELEGRAM_CHAT_ID': config_data['telegram']['chat_id'],
            'MARKET_DATA_INTERVAL': config_data['telegram'].get('market_data_interval', 300),
            'ENABLE_MARKET_DATA': config_data['telegram'].get('enable_market_data', True),
            
            # 核心策略参数
            'INITIAL_BALANCE': config_data['trading']['initial_balance'],
            'LEVERAGE': config_data['trading']['leverage'],
            'RISK_PERCENT': config_data['trading']['risk_percent'],
            'MAX_DAILY_TRADES': config_data['trading']['max_daily_trades'],
            'TRADE_INTERVAL': interval_map.get(config_data['trading']['trade_interval'], Client.KLINE_INTERVAL_15MINUTE),
            
            # 安全参数
            'MAX_SLIPPAGE': config_data['safety']['max_slippage'],
            'API_RETRIES': config_data['safety']['api_retries'],
            'API_TIMEOUT': config_data['safety']['api_timeout'],
            'MAX_OPEN_ORDERS': config_data['safety']['max_open_orders'],
            'MEMORY_LIMIT': config_data['safety']['memory_limit'],
            'VOLATILITY_FACTOR': config_data['safety']['volatility_factor'],
            
            # 风险控制
            'RISK_FLOOR': config_data['risk_control']['risk_floor'],
            'PROFIT_CEILING': config_data['risk_control']['profit_ceiling'],
            'DAILY_LOSS_LIMIT': config_data['risk_control']['daily_loss_limit'],
            'MAX_DRAWDOWN': config_data['risk_control']['max_drawdown'],
            
            # 系统参数
            'LOG_LEVEL': config_data['system']['log_level'],
            'LOG_MAX_SIZE': config_data['system']['log_max_size'],
            'LOG_BACKUP_COUNT': config_data['system']['log_backup_count'],
            'RECOVERY_SAVE_INTERVAL': config_data['system']['recovery_save_interval'],
            'SYSTEM_MONITOR_INTERVAL': config_data['system']['system_monitor_interval'],
            'PERFORMANCE_WINDOW': config_data['system']['performance_window']
        }
        
        # 交易品种配置
        TRADE_SYMBOLS = config_data['symbols']
        
        print("✅ 配置文件加载成功")
        return CONFIG, TRADE_SYMBOLS
        
    except FileNotFoundError:
        print("❌ 配置文件 config.json 未找到")
        print("请复制 config.json.example 为 config.json 并修改配置")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ 配置文件格式错误: {str(e)}")
        exit(1)
    except KeyError as e:
        print(f"❌ 配置文件缺少必要参数: {str(e)}")
        exit(1)
    except Exception as e:
        print(f"❌ 加载配置文件失败: {str(e)}")
        exit(1)

def validate_config(config, trade_symbols):
    """验证配置参数"""
    errors = []
    
    # 验证API密钥
    if config['API_KEY'] == 'YOUR_API_KEY' or config['API_SECRET'] == 'YOUR_API_SECRET':
        errors.append("请设置正确的API密钥")
    
    # 验证风险参数
    if not (0.01 <= config['RISK_PERCENT'] <= 0.05):
        errors.append("风险比例应在1%-5%之间")
    
    if not (1 <= config['LEVERAGE'] <= 5):
        errors.append("杠杆倍数应在1-5倍之间")
    
    # 验证交易品种
    if not trade_symbols:
        errors.append("至少需要配置一个交易品种")
    
    if errors:
        print("❌ 配置验证失败:")
        for error in errors:
            print(f"  - {error}")
        exit(1)
    
    print("✅ 配置验证通过")

# 加载配置
CONFIG, TRADE_SYMBOLS = load_config()
validate_config(CONFIG, TRADE_SYMBOLS)

# ======================
# 日志系统
# ======================
def setup_logger():
    """设置日志系统"""
    logger = logging.getLogger('trading_bot')
    logger.setLevel(getattr(logging, CONFIG['LOG_LEVEL']))
    
    handler = RotatingFileHandler(
        'trading.log', 
        maxBytes=CONFIG['LOG_MAX_SIZE'], 
        backupCount=CONFIG['LOG_BACKUP_COUNT']
    )
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

logger = setup_logger()

# ======================
# 网络会话配置
# ======================
session = requests.Session()
retry = Retry(
    total=CONFIG['API_RETRIES'],
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504]
)
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

# ======================
# 增强的币安客户端
# ======================
class EnhancedBinanceClient:
    def __init__(self, api_key, api_secret, testnet=False):
        self.client = Client(api_key, api_secret, testnet=testnet)
        self.last_call = time.time()
        self.call_count = 0
        
    def safe_request(self, func, *args, **kwargs):
        """带速率限制的安全请求"""
        # 速率限制
        elapsed = time.time() - self.last_call
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
            
        try:
            result = func(*args, **kwargs)
            self.last_call = time.time()
            self.call_count += 1
            return result
        except BinanceAPIException as e:
            self.handle_api_error(e)
            raise
        except Exception as e:
            logger.error(f"API调用异常: {str(e)}")
            raise
            
    def handle_api_error(self, error):
        """API错误处理"""
        error_codes = {
            -1003: "速率限制超过",
            -1015: "市场波动过大",
            -1021: "时间同步错误",
            -2010: "余额不足",
            -2019: "保证金不足"
        }
        msg = error_codes.get(error.code, f"未知错误: {error.code}")
        send_telegram(f"🚨 API错误: {msg}")
        logger.error(f"API错误 {error.code}: {msg}")

# 初始化增强客户端
client = EnhancedBinanceClient(CONFIG['API_KEY'], CONFIG['API_SECRET'], CONFIG['TESTNET'])

# ======================
# 系统监控装饰器
# ======================
def system_guard(func):
    """系统资源监控装饰器"""
    def wrapper(*args, **kwargs):
        # 内存检查
        memory_percent = psutil.virtual_memory().percent
        if memory_percent > CONFIG['MEMORY_LIMIT']:
            send_telegram(f"🛑 系统内存使用{memory_percent:.1f}%，暂停操作")
            return None
            
        # 线程检查
        if threading.active_count() > 15:
            send_telegram("🛑 线程数过多，系统过载")
            return None
            
        return func(*args, **kwargs)
    return wrapper

# ======================
# 工具函数增强
# ======================
def send_telegram(message, silent=False):
    """增强的Telegram通知"""
    if CONFIG['TELEGRAM_TOKEN'] and CONFIG['TELEGRAM_CHAT_ID']:
        try:
            url = f"https://api.telegram.org/bot{CONFIG['TELEGRAM_TOKEN']}/sendMessage"
            payload = {
                'chat_id': CONFIG['TELEGRAM_CHAT_ID'],
                'text': message,
                'parse_mode': 'HTML',
                'disable_notification': silent  # 静默通知选项
            }
            session.post(url, json=payload, timeout=5)
            if not silent:  # 只有非静默消息才记录到日志
                logger.info(f"Telegram消息已发送: {message}")
        except Exception as e:
            logger.error(f"Telegram发送失败: {str(e)}")
    if not silent:  # 只有非静默消息才打印到控制台
        print(message)

def send_market_data_telegram(symbol, price, indicators, market_state):
    """发送市场数据到Telegram"""
    try:
        # 格式化指标信息
        rsi = indicators.get('rsi', 0)
        atr = indicators.get('atr', 0)
        adx = indicators.get('adx', 0)
        volume_ratio = indicators.get('volume_ratio', 0)
        
        # 确定RSI状态
        rsi_status = "🔥超买" if rsi > 70 else "❄️超卖" if rsi < 30 else "⚖️中性"
        
        # 确定趋势强度
        trend_strength = "💪强趋势" if adx > 25 else "📈弱趋势" if adx > 20 else "📊震荡"
        
        # 确定成交量状态
        volume_status = "📈活跃" if volume_ratio > 1.2 else "📉低迷" if volume_ratio < 0.8 else "➡️正常"
        
        # 市场状态emoji
        state_emoji = {
            'TRENDING': '📈',
            'OVERSOLD': '🟢', 
            'OVERBOUGHT': '🔴',
            'RANGING': '↔️'
        }
        
        message = f"""
📊 <b>{symbol} 市场数据</b>

💰 <b>价格:</b> ${price:.4f}
📈 <b>市场状态:</b> {state_emoji.get(market_state, '❓')} {market_state}

🔍 <b>技术指标:</b>
├ RSI: {rsi:.1f} {rsi_status}
├ ADX: {adx:.1f} {trend_strength}  
├ ATR: {atr:.4f}
└ 成交量: {volume_ratio:.2f}x {volume_status}

⏰ {datetime.now().strftime('%H:%M:%S')}
        """.strip()
        
        send_telegram(message, silent=True)  # 静默发送，避免过多通知
        
    except Exception as e:
        logger.error(f"发送市场数据失败: {str(e)}")

def send_signal_analysis_telegram(symbol, signal_data):
    """发送交易信号分析到Telegram"""
    try:
        signal_type = signal_data.get('type', 'NONE')
        signal_action = signal_data.get('signal', 'NONE')
        confidence = signal_data.get('confidence', 0)
        reason = signal_data.get('reason', '无信号')
        
        # 获取详细指标信息
        price = signal_data.get('price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        take_profit = signal_data.get('take_profit', 0)
        position_size = signal_data.get('size', 0)
        rsi = signal_data.get('rsi', 0)
        atr = signal_data.get('atr', 0)
        volume_ratio = signal_data.get('volume_ratio', 0)
        market_state = signal_data.get('market_state', 'UNKNOWN')
        
        if signal_action == 'BUY':
            # 计算风险回报比
            risk = price - stop_loss
            reward = take_profit - price
            rr_ratio = reward / risk if risk > 0 else 0
            
            # 策略emoji
            strategy_emoji = "🚀" if signal_type == "MOMENTUM" else "🔄"
            
            # 信号强度条
            confidence_bar = "🟩" * int(confidence/20) + "⬜" * (5-int(confidence/20))
            
            # 风险等级
            if confidence >= 80:
                risk_level = "🟢 低风险"
            elif confidence >= 60:
                risk_level = "🟡 中风险"
            else:
                risk_level = "🔴 高风险"
                
            # 市场状态emoji
            state_emoji = {
                'TRENDING': '📈',
                'OVERSOLD': '🟢', 
                'OVERBOUGHT': '🔴',
                'RANGING': '↔️'
            }
            
            message = f"""
{strategy_emoji} <b>{symbol} 交易信号确认</b>

📋 <b>策略类型:</b> {signal_type}
📊 <b>信号强度:</b> {confidence:.1f}% {confidence_bar}
🎯 <b>风险等级:</b> {risk_level}

💰 <b>交易详情:</b>
├ 入场价格: ${price:.4f}
├ 止损价格: ${stop_loss:.4f}
├ 止盈价格: ${take_profit:.4f}
├ 仓位大小: {position_size:.4f}
└ 风险回报比: 1:{rr_ratio:.2f}

🔍 <b>技术分析:</b>
├ RSI: {rsi:.1f}
├ ATR: {atr:.4f}
├ 成交量: {volume_ratio:.2f}x
└ 市场状态: {state_emoji.get(market_state, '❓')} {market_state}

📝 <b>信号依据:</b> {reason}

⏰ {datetime.now().strftime('%H:%M:%S')}
            """.strip()
            
            send_telegram(message)  # 正常发送，重要信号
        
    except Exception as e:
        logger.error(f"发送信号分析失败: {str(e)}")

def send_trade_execution_telegram(symbol, order_result, signal_data):
    """发送交易执行结果到Telegram"""
    try:
        if order_result and order_result.get('success'):
            order_info = order_result.get('order', {})
            
            message = f"""
✅ <b>{symbol} 交易执行成功</b>

📋 <b>订单信息:</b>
├ 订单ID: {order_info.get('orderId', 'N/A')}
├ 交易类型: {signal_data.get('type', 'UNKNOWN')}
├ 成交价格: ${float(order_info.get('price', 0)):.4f}
├ 成交数量: {float(order_info.get('executedQty', 0)):.4f}
└ 订单状态: {order_info.get('status', 'UNKNOWN')}

📊 <b>风控设置:</b>
├ 止损价格: ${signal_data.get('stop_loss', 0):.4f}
└ 止盈价格: ${signal_data.get('take_profit', 0):.4f}

⏰ {datetime.now().strftime('%H:%M:%S')}
            """.strip()
            
        else:
            error_msg = order_result.get('error', '未知错误') if order_result else '执行失败'
            
            message = f"""
❌ <b>{symbol} 交易执行失败</b>

🚨 <b>错误原因:</b> {error_msg}
📋 <b>信号类型:</b> {signal_data.get('type', 'UNKNOWN')}
💰 <b>尝试价格:</b> ${signal_data.get('price', 0):.4f}

⏰ {datetime.now().strftime('%H:%M:%S')}
            """.strip()
            
        send_telegram(message)
        
    except Exception as e:
        logger.error(f"发送交易执行通知失败: {str(e)}")

def get_current_price(symbol, retries=3):
    """增强的价格获取容错机制"""
    for i in range(retries):
        try:
            if CONFIG['TRADING_TYPE'] == 'futures':
                ticker = client.safe_request(
                    client.client.futures_symbol_ticker, symbol=symbol
                )
            else:  # spot
                ticker = client.safe_request(
                    client.client.get_symbol_ticker, symbol=symbol
                )
            return float(ticker['price'])
        except Exception as e:
            logger.warning(f"获取{symbol}价格失败(尝试{i+1}/{retries}): {str(e)}")
            if i == retries - 1:
                # 备用方案：使用最近K线价格
                try:
                    df = fetch_klines(symbol, '1m', 1)
                    if df is not None and not df.empty:
                        backup_price = df['close'].iloc[-1]
                        logger.info(f"使用备用价格获取方式: {symbol} = {backup_price}")
                        return backup_price
                except Exception as backup_e:
                    logger.error(f"备用价格获取也失败: {str(backup_e)}")
            time.sleep(0.5)
    return None

# ======================
# 增强的数据获取
# ======================
@system_guard
def fetch_klines(symbol, interval, limit=100):
    """带数据完整性检查的K线获取"""
    try:
        if CONFIG['TRADING_TYPE'] == 'futures':
            klines = client.safe_request(
                client.client.futures_klines,
                symbol=symbol, interval=interval, limit=limit
            )
        else:  # spot
            klines = client.safe_request(
                client.client.get_klines,
                symbol=symbol, interval=interval, limit=limit
            )
        
        # 数据完整性检查
        if len(klines) < limit * 0.9:
            logger.warning(f"{symbol}数据不完整: {len(klines)}/{limit}")
            return None
            
        df = pd.DataFrame(klines, columns=pd.Index([
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ]))
        
        # 数据类型转换
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, axis=1)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df.set_index('timestamp')
    except Exception as e:
        logger.error(f"获取{symbol}K线失败: {str(e)}")
        return None

def calculate_indicators(df):
    """增强的技术指标计算"""
    if df is None or len(df) < 50:
        return None
    
    try:
        # 基础指标
        df['momentum'] = df['close'] / df['close'].shift(20) - 1
        
        # RSI指标 - 使用Wilder's平滑法
        df['rsi'] = calculate_rsi_accurate(df['close'], 14)
        
        # ATR指标 - 真实波动范围
        df['atr'] = calculate_atr_accurate(df['high'], df['low'], df['close'], 14)
        
        # 指数移动平均
        df['ema30'] = calculate_ema_accurate(df['close'], 30)
        df['ema50'] = calculate_ema_accurate(df['close'], 50)
        
        # 布林带
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = calculate_bollinger_bands(df['close'], 20, 2)
        
        # 成交量指标
        df['volume_ma20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma20']
        
        # ADX趋势强度指标
        df['adx'] = calculate_adx_accurate(df['high'], df['low'], df['close'], 14)
        
        # 市场状态检测
        df['market_state'] = df.apply(lambda row: detect_market_regime(row), axis=1)
        
        return df.dropna()
    except Exception as e:
        logger.error(f"指标计算失败: {str(e)}")
        return None

def calculate_rsi_accurate(close, period=14):
    """
    精确计算RSI指标 - 使用Wilder's平滑方法
    """
    delta = close.diff()
    
    # 分离上涨和下跌
    gains = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)
    
    # 使用Wilder's平滑方法 (alpha = 1/period)
    alpha = 1.0 / period
    
    # 计算平均增益和平均损失
    avg_gains = gains.ewm(alpha=alpha, adjust=False).mean()
    avg_losses = losses.ewm(alpha=alpha, adjust=False).mean()
    
    # 计算相对强度和RSI
    rs = avg_gains / avg_losses
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def calculate_ema_accurate(close, period):
    """
    精确计算指数移动平均 - 标准EMA算法
    """
    alpha = 2.0 / (period + 1)
    return close.ewm(alpha=alpha, adjust=False).mean()

def calculate_atr_accurate(high, low, close, period=14):
    """
    精确计算平均真实范围(ATR) - Wilder's方法
    """
    # 计算真实范围的三个组成部分
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    
    # 真实范围是三者中的最大值
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 使用Wilder's平滑方法计算ATR
    alpha = 1.0 / period
    atr = true_range.ewm(alpha=alpha, adjust=False).mean()
    
    return atr

def calculate_bollinger_bands(close, period=20, std_dev=2):
    """
    精确计算布林带
    """
    # 中轨：简单移动平均
    middle = close.rolling(period).mean()
    
    # 标准差
    std = close.rolling(period).std()
    
    # 上轨和下轨
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower

def calculate_adx_accurate(high, low, close, period=14):
    """
    精确计算ADX指标 - 使用标准Wilder's方法
    """
    # 计算真实范围
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # 计算方向运动
    dm_plus = high.diff()
    dm_minus = low.diff() * -1
    
    # 只保留有效的方向运动
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0)
    
    # 使用Wilder's平滑
    alpha = 1.0 / period
    
    atr_smooth = true_range.ewm(alpha=alpha, adjust=False).mean()
    dm_plus_smooth = dm_plus.ewm(alpha=alpha, adjust=False).mean()
    dm_minus_smooth = dm_minus.ewm(alpha=alpha, adjust=False).mean()
    
    # 计算方向指标
    di_plus = 100 * (dm_plus_smooth / atr_smooth)
    di_minus = 100 * (dm_minus_smooth / atr_smooth)
    
    # 计算DX
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus)
    
    # 计算ADX (DX的平滑值)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    
    return adx

def detect_market_regime(row):
    """市场状态检测器"""
    try:
        # 使用ADX识别趋势强度
        adx = row['adx']
        bb_position = (row['close'] - row['bb_lower']) / (row['bb_upper'] - row['bb_lower'])
        
        if pd.isna(adx):
            return 'UNKNOWN'
        
        if adx > 25:
            return 'TRENDING'
        elif bb_position < 0.3:
            return 'OVERSOLD'
        elif bb_position > 0.7:
            return 'OVERBOUGHT'
        else:
            return 'RANGING'
    except Exception:
        return 'UNKNOWN'

# ======================
# 订单管理器
# ======================
class OrderManager:
    def __init__(self):
        self.open_orders = {}
        self.position_lock = threading.Lock()
        self.order_timeouts = {}
        self.trade_history = []
        
    @system_guard
    def execute_order(self, signal):
        """全生命周期订单管理"""
        with self.position_lock:
            if not self._pre_execution_check(signal):
                return {'success': False, 'error': '执行前检查失败'}
                
            try:
                # 执行主订单
                main_order = self._place_main_order(signal)
                if not main_order:
                    return {'success': False, 'error': '主订单执行失败'}
                    
                # 设置风控订单
                self._place_risk_orders(signal, main_order)
                
                # 记录订单
                order_id = main_order['orderId']
                self.open_orders[order_id] = {
                    'signal': signal,
                    'order': main_order,
                    'timestamp': time.time()
                }
                
                # 启动订单监控线程
                monitor_thread = threading.Thread(
                    target=self._monitor_order, 
                    args=(order_id, signal)
                )
                monitor_thread.daemon = True
                monitor_thread.start()
                
                return {'success': True, 'order': main_order}
            except Exception as e:
                error_msg = str(e)
                logger.error(f"订单执行失败: {error_msg}")
                send_telegram(f"❌ 订单执行失败: {error_msg}")
                return {'success': False, 'error': error_msg}
                
    def _pre_execution_check(self, signal):
        """执行前检查"""
        # 滑点检查
        current_price = get_current_price(signal['symbol'])
        if not current_price:
            return False
            
        slippage = abs(current_price - signal['price']) / signal['price']
        if slippage > CONFIG['MAX_SLIPPAGE']:
            send_telegram(f"🚫 {signal['symbol']} 滑点过大: {slippage:.2%}")
            return False
            
        # 保证金检查
        account_balance = self._get_account_balance()
        required_margin = (signal['size'] * current_price) / CONFIG['LEVERAGE']
        if required_margin > account_balance * 0.8:
            send_telegram(f"💰 保证金不足: 需要{required_margin:.2f}")
            return False
            
        # 挂单数量检查
        if len(self.open_orders) >= CONFIG['MAX_OPEN_ORDERS']:
            send_telegram("📊 活跃订单过多，暂停交易")
            return False
            
        return True
    
    def _place_main_order(self, signal):
        """下主订单"""
        try:
            if CONFIG['TRADING_TYPE'] == 'futures':
                order = client.safe_request(
                    client.client.futures_create_order,
                    symbol=signal['symbol'],
                    side=SIDE_BUY,
                    type=FUTURE_ORDER_TYPE_MARKET,
                    quantity=signal['size']
                )
            else:  # spot
                order = client.safe_request(
                    client.client.order_market_buy,
                    symbol=signal['symbol'],
                    quantity=signal['size']
                )
            
            send_telegram(
                f"✅ {signal['symbol']} 开仓成功\n"
                f"类型: {signal['type']}\n"
                f"数量: {signal['size']}\n"
                f"价格: ${signal['price']:.2f}"
            )
            return order
        except Exception as e:
            logger.error(f"主订单失败: {str(e)}")
            return None
    
    def _place_risk_orders(self, signal, main_order):
        """设置风控订单"""
        try:
            # 止损单
            client.safe_request(
                client.client.futures_create_order,
                symbol=signal['symbol'],
                side=SIDE_SELL,
                type=FUTURE_ORDER_TYPE_STOP_MARKET,
                stopPrice=round(signal['stop_loss'], 2),
                closePosition=True
            )
            
            # 止盈单
            client.safe_request(
                client.client.futures_create_order,
                symbol=signal['symbol'],
                side=SIDE_SELL,
                type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
                stopPrice=round(signal['take_profit'], 2),
                closePosition=True
            )
            
        except Exception as e:
            logger.error(f"风控订单设置失败: {str(e)}")
    
    def _get_account_balance(self):
        """获取账户余额"""
        try:
            if CONFIG['TRADING_TYPE'] == 'futures':
                balance = client.safe_request(client.client.futures_account_balance)
                for asset in balance:
                    if asset['asset'] == 'USDT':
                        return float(asset['balance'])
            else:  # spot
                account = client.safe_request(client.client.get_account)
                for balance in account['balances']:
                    if balance['asset'] == 'USDT':
                        return float(balance['free'])
        except Exception as e:
            logger.error(f"获取余额失败: {str(e)}")
        return CONFIG['INITIAL_BALANCE']
    
    def _monitor_order(self, order_id, signal):
        """订单生命周期监控"""
        start_time = time.time()
        symbol = signal['symbol']
        
        while time.time() - start_time < 120:  # 2分钟超时
            try:
                if CONFIG['TRADING_TYPE'] == 'futures':
                    order_status = client.safe_request(
                        client.client.futures_get_order,
                        symbol=symbol,
                        orderId=order_id
                    )
                else:  # spot
                    order_status = client.safe_request(
                        client.client.get_order,
                        symbol=symbol,
                        orderId=order_id
                    )
                
                status = order_status['status']
                
                if status == 'FILLED':
                    # 订单完成，记录交易历史
                    self.trade_history.append({
                        'symbol': symbol,
                        'side': 'BUY',
                        'size': float(order_status['executedQty']),
                        'price': float(order_status['avgPrice']),
                        'timestamp': time.time(),
                        'signal_type': signal['type']
                    })
                    
                    if order_id in self.open_orders:
                        del self.open_orders[order_id]
                    
                    send_telegram(f"✅ {symbol} 订单已成交 (ID: {order_id})")
                    return True
                    
                elif status == 'CANCELED':
                    if order_id in self.open_orders:
                        del self.open_orders[order_id]
                    send_telegram(f"❌ {symbol} 订单已取消 (ID: {order_id})")
                    return False
                    
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"订单监控异常: {str(e)}")
                time.sleep(5)
        
        # 超时处理
        try:
            if CONFIG['TRADING_TYPE'] == 'futures':
                client.safe_request(
                    client.client.futures_cancel_order,
                    symbol=symbol,
                    orderId=order_id
                )
            else:  # spot
                client.safe_request(
                    client.client.cancel_order,
                    symbol=symbol,
                    orderId=order_id
                )
            send_telegram(f"⏰ {symbol} 订单超时已取消 (ID: {order_id})")
        except Exception as e:
            logger.error(f"取消超时订单失败: {str(e)}")
        
        if order_id in self.open_orders:
            del self.open_orders[order_id]
        
        return False

# ======================
# 自动参数优化器
# ======================
class ParameterOptimizer:
    def __init__(self):
        self.performance_window = CONFIG['PERFORMANCE_WINDOW']  # 从配置文件读取
        
    def optimize_risk(self, recent_trades):
        """基于近期表现动态调整风险参数"""
        if len(recent_trades) < 10:
            return CONFIG['RISK_PERCENT']
        
        # 取最近的交易记录
        recent = recent_trades[-self.performance_window:]
        
        # 计算胜率
        profitable_trades = [t for t in recent if self._calculate_pnl(t) > 0]
        win_rate = len(profitable_trades) / len(recent)
        
        # 计算平均盈亏比
        avg_profit = np.mean([self._calculate_pnl(t) for t in profitable_trades]) if profitable_trades else 0
        losing_trades = [t for t in recent if self._calculate_pnl(t) < 0]
        avg_loss = abs(np.mean([self._calculate_pnl(t) for t in losing_trades])) if losing_trades else 1
        
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 1
        
        # 动态调整风险
        base_risk = CONFIG['RISK_PERCENT']
        
        if win_rate > 0.7 and profit_loss_ratio > 1.5:
            # 表现优异，适度增加风险
            adjusted_risk = min(base_risk * 1.2, 0.035)
            logger.info(f"性能优异，风险调整至 {adjusted_risk*100:.2f}%")
        elif win_rate < 0.4 or profit_loss_ratio < 0.8:
            # 表现不佳，降低风险
            adjusted_risk = max(base_risk * 0.8, 0.015)
            logger.info(f"性能不佳，风险调整至 {adjusted_risk*100:.2f}%")
        else:
            adjusted_risk = base_risk
            
        return adjusted_risk
    
    def _calculate_pnl(self, trade):
        """计算单笔交易盈亏（简化版）"""
        # 这里需要根据实际的交易结构来计算
        # 简化处理，假设trade包含entry_price和exit_price
        if 'pnl' in trade:
            return trade['pnl']
        else:
            # 基于价格估算盈亏
            return 0  # 需要实际实现

# ======================
# 灾难恢复机制
# ======================
def save_recovery_state(order_manager):
    """保存系统状态用于灾难恢复"""
    try:
        # 根据交易类型获取持仓和订单信息
        if CONFIG['TRADING_TYPE'] == 'futures':
            # 期货交易：获取持仓信息
            positions = client.safe_request(client.client.futures_position_information)
            active_positions = [pos for pos in positions if float(pos['positionAmt']) != 0]
            
            # 获取活跃订单
            active_orders = client.safe_request(client.client.futures_get_open_orders)
        else:  # spot
            # 现货交易：获取余额信息（现货没有持仓概念）
            account = client.safe_request(client.client.get_account)
            active_positions = [balance for balance in account['balances'] if float(balance['free']) > 0 or float(balance['locked']) > 0]
            
            # 获取活跃订单
            active_orders = client.safe_request(client.client.get_open_orders)
        
        recovery_data = {
            'positions': active_positions,
            'orders': active_orders,
            'open_orders': order_manager.open_orders,
            'trade_history': order_manager.trade_history[-50:],  # 保存最近50笔交易
            'timestamp': time.time(),
            'config': CONFIG,
            'trading_type': CONFIG['TRADING_TYPE']  # 保存交易类型信息
        }
        
        with open('recovery.json', 'w') as f:
            json.dump(recovery_data, f, indent=2, default=str)
            
        logger.info("恢复状态已保存")
        
    except Exception as e:
        logger.error(f"保存恢复状态失败: {str(e)}")

def load_recovery_state():
    """系统崩溃后恢复状态"""
    try:
        if not os.path.exists('recovery.json'):
            return None
            
        with open('recovery.json', 'r') as f:
            state = json.load(f)
            
        # 检查状态文件的有效性（1小时内）
        if time.time() - state['timestamp'] > 3600:
            logger.warning("恢复状态文件已过期")
            return None
            
        logger.info("发现有效的恢复状态文件")
        return state
        
    except Exception as e:
        logger.error(f"加载恢复状态失败: {str(e)}")
        return None

def recover_system_state(order_manager, recovery_state):
    """恢复系统状态"""
    try:
        # 恢复交易历史
        if 'trade_history' in recovery_state:
            order_manager.trade_history = recovery_state['trade_history']
            
        # 恢复订单状态
        if 'open_orders' in recovery_state:
            order_manager.open_orders = recovery_state['open_orders']
            
        # 根据交易类型检查状态
        trading_type = recovery_state.get('trading_type', CONFIG['TRADING_TYPE'])
        
        if trading_type == 'futures':
            # 期货：检查持仓状态
            current_positions = client.safe_request(client.client.futures_position_information)
            active_positions_count = len([p for p in current_positions if float(p['positionAmt']) != 0])
            status_msg = f"当前持仓: {active_positions_count}个"
        else:  # spot
            # 现货：检查余额状态
            account = client.safe_request(client.client.get_account)
            active_balances = [b for b in account['balances'] if float(b['free']) > 0 or float(b['locked']) > 0]
            status_msg = f"当前余额: {len(active_balances)}种资产"
        
        send_telegram(
            f"🔄 系统状态已恢复\n"
            f"交易类型: {'期货' if trading_type == 'futures' else '现货'}\n"
            f"历史交易: {len(order_manager.trade_history)}笔\n"
            f"活跃订单: {len(order_manager.open_orders)}个\n"
            f"{status_msg}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"恢复系统状态失败: {str(e)}")
        return False

# ======================
# 信号生成增强
# ======================
@system_guard
def generate_signal(df, symbol, current_balance, trade_history=None):
    """增强的信号生成"""
    if df is None or len(df) < 2:
        return None
    
    try:
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 波动率检查
        if current['atr'] > df['atr'].mean() * CONFIG['VOLATILITY_FACTOR']:
            logger.warning(f"{symbol} 波动率过高，跳过信号")
            return None
        
        # 动量信号 - 增加成交量确认
        momentum_signal = all([
            current['momentum'] > 0.05,
            current['rsi'] < 70,
            current['close'] > current['bb_upper'],
            current['ema30'] > current['ema50'],
            current['volume_ratio'] > 1.2,  # 成交量放大
            current['market_state'] == 'TRENDING'
        ])
        
        # 波段信号 - 增加趋势确认
        swing_signal = all([
            current['rsi'] < 40,
            current['close'] < current['bb_lower'],
            current['ema30'] > current['ema50'],
            current['volume_ratio'] > 1.1
        ])
        
        # 仓位计算（使用动态风险参数）
        position_size = calculate_position_size(
            symbol, current_balance,
            'MOMENTUM' if momentum_signal else 'SWING',
            current['atr'], current['close'], trade_history
        )
        
        if not position_size:
            return None
        
        # 计算信号强度和分析原因
        if momentum_signal:
            # 计算动量信号强度
            strength_factors = {
                'momentum': min(current['momentum'] * 10, 25),  # 最大25分
                'rsi': max(0, 30 - (current['rsi'] - 50)) / 30 * 20,  # 最大20分
                'bb_breakout': 15 if current['close'] > current['bb_upper'] else 0,  # 15分
                'ema_trend': 15 if current['ema30'] > current['ema50'] else 0,  # 15分
                'volume': min((current['volume_ratio'] - 1) * 25, 25),  # 最大25分
                'market_state': 10 if current['market_state'] == 'TRENDING' else 0  # 10分
            }
            
            confidence = sum(strength_factors.values())
            
            reasons = []
            if strength_factors['momentum'] > 0:
                reasons.append(f"动量突破({current['momentum']:.2%})")
            if strength_factors['bb_breakout'] > 0:
                reasons.append("布林带上轨突破")
            if strength_factors['ema_trend'] > 0:
                reasons.append("EMA多头排列")
            if strength_factors['volume'] > 0:
                reasons.append(f"成交量放大({current['volume_ratio']:.1f}x)")
            if strength_factors['market_state'] > 0:
                reasons.append("趋势市场确认")
            
            return {
                'symbol': symbol,
                'signal': 'BUY',
                'type': 'MOMENTUM',
                'size': position_size,
                'price': current['close'],
                'stop_loss': current['close'] - TRADE_SYMBOLS[symbol]['stop_multiplier']['MOMENTUM'] * current['atr'],
                'take_profit': current['close'] + TRADE_SYMBOLS[symbol]['profit_multiplier']['MOMENTUM'] * current['atr'],
                'confidence': min(confidence, 100),  # 限制最大100%
                'reason': ' + '.join(reasons),
                'rsi': current['rsi'],
                'atr': current['atr'],
                'volume_ratio': current['volume_ratio'],
                'market_state': current['market_state']
            }
            
        elif swing_signal:
            # 计算波段信号强度
            strength_factors = {
                'rsi_oversold': max(0, (40 - current['rsi']) / 40 * 30),  # 最大30分
                'bb_support': 20 if current['close'] < current['bb_lower'] else 0,  # 20分
                'ema_trend': 15 if current['ema30'] > current['ema50'] else 0,  # 15分
                'volume': min((current['volume_ratio'] - 1) * 20, 20),  # 最大20分
                'mean_reversion': 15  # 均值回归基础分
            }
            
            confidence = sum(strength_factors.values())
            
            reasons = []
            if strength_factors['rsi_oversold'] > 0:
                reasons.append(f"RSI超卖({current['rsi']:.1f})")
            if strength_factors['bb_support'] > 0:
                reasons.append("布林带下轨支撑")
            if strength_factors['ema_trend'] > 0:
                reasons.append("EMA多头排列")
            if strength_factors['volume'] > 0:
                reasons.append(f"成交量配合({current['volume_ratio']:.1f}x)")
            reasons.append("均值回归机会")
            
            return {
                'symbol': symbol,
                'signal': 'BUY',
                'type': 'SWING',
                'size': position_size,
                'price': current['close'],
                'stop_loss': current['close'] - TRADE_SYMBOLS[symbol]['stop_multiplier']['SWING'] * current['atr'],
                'take_profit': current['close'] + TRADE_SYMBOLS[symbol]['profit_multiplier']['SWING'] * current['atr'],
                'confidence': min(confidence, 100),  # 限制最大100%
                'reason': ' + '.join(reasons),
                'rsi': current['rsi'],
                'atr': current['atr'],
                'volume_ratio': current['volume_ratio'],
                'market_state': current['market_state']
            }
        
        return None
    except Exception as e:
        logger.error(f"信号生成失败: {str(e)}")
        return None

def calculate_position_size(symbol, balance, signal_type, atr, price, trade_history=None):
    """改进的仓位计算（含动态风险调整）"""
    try:
        # 获取动态调整的风险参数
        if trade_history and len(trade_history) > 0:
            optimizer = ParameterOptimizer()
            risk_percent = optimizer.optimize_risk(trade_history)
        else:
            risk_percent = CONFIG['RISK_PERCENT']
        
        # 基础风险金额
        base_risk = balance * risk_percent * TRADE_SYMBOLS[symbol]['risk_weight']
        
        # 根据波动率调整
        volatility_adj = min(atr / price * 100, 5.0)  # 限制最大调整
        adjusted_risk = base_risk * (1 - volatility_adj * 0.1)
        
        # 计算仓位
        multiplier = TRADE_SYMBOLS[symbol]['stop_multiplier'][signal_type]
        position_size = adjusted_risk / (multiplier * atr)
        
        # 转换为合约数量
        if symbol.endswith('USDT'):
            position_size = position_size / price
        
        # 限制最大持仓
        max_position = TRADE_SYMBOLS[symbol]['max_position_usd'] / price
        position_size = min(position_size, max_position)
        
        # 最小交易量检查
        min_qty = TRADE_SYMBOLS[symbol]['min_qty']
        if position_size < min_qty:
            return None
            
        return round(position_size, 5)
    except Exception as e:
        logger.error(f"仓位计算失败: {str(e)}")
        return None

# ======================
# 系统监控
# ======================
def system_monitor():
    """系统实时监控"""
    while True:
        try:
            # API延迟检测
            start_time = time.time()
            if CONFIG['TRADING_TYPE'] == 'futures':
                client.safe_request(client.client.futures_ping)
            else:  # spot
                client.safe_request(client.client.ping)
            latency = (time.time() - start_time) * 1000
            
            if latency > 500:
                send_telegram(f"⚠️ API延迟过高: {latency:.0f}ms")
            
            # 系统资源监控
            memory_percent = psutil.virtual_memory().percent
            cpu_percent = psutil.cpu_percent()
            
            if memory_percent > 80:
                send_telegram(f"🔴 内存使用{memory_percent:.1f}%")
            if cpu_percent > 90:
                send_telegram(f"🔴 CPU使用{cpu_percent:.1f}%")
                
            time.sleep(CONFIG['SYSTEM_MONITOR_INTERVAL'])  # 从配置文件读取间隔
        except Exception as e:
            logger.error(f"系统监控异常: {str(e)}")
            time.sleep(60)

# ======================
# 初始化函数
# ======================
def initialize_account():
    """账户初始化"""
    if CONFIG['TRADING_TYPE'] == 'futures':
        logger.info("开始初始化期货账户...")
        
        for symbol in TRADE_SYMBOLS:
            try:
                # 先获取当前持仓信息，检查保证金类型
                try:
                    position_info = client.safe_request(
                        client.client.futures_position_information,
                        symbol=symbol
                    )
                    current_margin_type = position_info[0].get('marginType', 'isolated').lower()
                    
                    # 只有在不是隔离保证金时才设置
                    if current_margin_type != 'isolated':
                        client.safe_request(
                            client.client.futures_change_margin_type,
                            symbol=symbol, marginType='ISOLATED'
                        )
                        logger.info(f"{symbol} 保证金类型已设置为隔离模式")
                    else:
                        logger.info(f"{symbol} 已是隔离保证金模式")
                        
                except Exception as margin_e:
                    if "No need to change margin type" in str(margin_e):
                        logger.info(f"{symbol} 保证金类型已正确设置")
                    else:
                        logger.warning(f"{symbol} 保证金设置警告: {str(margin_e)}")
                
                # 设置杠杆（总是尝试设置，因为可能需要调整）
                try:
                    client.safe_request(
                        client.client.futures_change_leverage,
                        symbol=symbol, leverage=CONFIG['LEVERAGE']
                    )
                    logger.info(f"{symbol} 杠杆已设置为 {CONFIG['LEVERAGE']}x")
                except Exception as leverage_e:
                    if "leverage not modified" in str(leverage_e).lower():
                        logger.info(f"{symbol} 杠杆已是 {CONFIG['LEVERAGE']}x")
                    else:
                        logger.warning(f"{symbol} 杠杆设置警告: {str(leverage_e)}")
                
                logger.info(f"{symbol} 期货初始化完成")
                
            except Exception as e:
                logger.error(f"{symbol} 期货初始化失败: {str(e)}")
                send_telegram(f"❌ {symbol} 期货初始化失败: {str(e)}")
    else:  # spot
        logger.info("开始初始化现货账户...")
        
        try:
            # 获取账户信息验证连接
            account = client.safe_request(client.client.get_account)
            logger.info("现货账户连接成功")
            
            # 显示主要余额
            for balance in account['balances']:
                free = float(balance['free'])
                if free > 0:
                    logger.info(f"{balance['asset']}: {free}")
                    
        except Exception as e:
            logger.error(f"现货账户初始化失败: {str(e)}")
            send_telegram(f"❌ 现货账户初始化失败: {str(e)}")

# ======================
# 主程序
# ======================
def main():
    """主交易循环"""
    logger.info("交易机器人启动")
    
    # 检查并恢复系统状态
    recovery_state = load_recovery_state()
    
    # 初始化
    initialize_account()
    order_manager = OrderManager()
    
    # 如果有恢复状态，则恢复系统
    if recovery_state:
        recover_system_state(order_manager, recovery_state)
    
    # 启动系统监控
    monitor_thread = threading.Thread(target=system_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # 发送启动通知
    market_data_status = "✅ 开启" if CONFIG['ENABLE_MARKET_DATA'] else "❌ 关闭"
    interval_text = f"每{CONFIG['MARKET_DATA_INTERVAL']//60}分钟" if CONFIG['ENABLE_MARKET_DATA'] else "不推送"
    
    send_telegram(
        f"🚀 <b>交易机器人启动</b>\n"
        f"版本: 1.0 \n"
        f"杠杆: {CONFIG['LEVERAGE']}x\n"
        f"风险: {CONFIG['RISK_PERCENT']*100:.2f}%\n"
        f"币种: {', '.join(TRADE_SYMBOLS.keys())}\n"
        f"📊 市场数据推送: {market_data_status}\n"
        f"⏰ 推送频率: {interval_text}"
    )
    
    # 主循环变量
    daily_trade_count = 0
    last_trade_day = datetime.now().strftime('%Y-%m-%d')
    last_save_time = time.time()
    last_market_data_time = {}  # 记录每个交易对上次发送市场数据的时间
    
    while True:
        try:
            current_day = datetime.now().strftime('%Y-%m-%d')
            
            # 新的一天重置计数
            if current_day != last_trade_day:
                daily_trade_count = 0
                last_trade_day = current_day
                send_telegram(f"📅 新的交易日开始: {current_day}")
            
            # 每日交易限制检查
            if daily_trade_count >= CONFIG['MAX_DAILY_TRADES']:
                time.sleep(3600)  # 等待1小时
                continue
            
            # 遍历交易对
            for symbol in TRADE_SYMBOLS:
                # 获取当前价格
                current_price = get_current_price(symbol)
                if current_price is None:
                    continue
                
                # 获取数据
                df = fetch_klines(symbol, CONFIG['TRADE_INTERVAL'])
                if df is None:
                    continue
                
                # 计算指标
                df = calculate_indicators(df)
                if df is None:
                    continue
                
                # 获取最新指标数据
                latest_data = df.iloc[-1]
                indicators = {
                    'rsi': latest_data.get('rsi', 0),
                    'atr': latest_data.get('atr', 0),
                    'adx': latest_data.get('adx', 0),
                    'volume_ratio': latest_data.get('volume_ratio', 0),
                    'ema30': latest_data.get('ema30', 0),
                    'ema50': latest_data.get('ema50', 0),
                    'bb_upper': latest_data.get('bb_upper', 0),
                    'bb_lower': latest_data.get('bb_lower', 0)
                }
                
                market_state = latest_data.get('market_state', 'UNKNOWN')
                
                # 发送市场数据到Telegram（控制频率）
                if CONFIG['ENABLE_MARKET_DATA']:
                    current_time = time.time()
                    if (symbol not in last_market_data_time or 
                        current_time - last_market_data_time[symbol] >= CONFIG['MARKET_DATA_INTERVAL']):
                        send_market_data_telegram(symbol, current_price, indicators, market_state)
                        last_market_data_time[symbol] = current_time
                
                # 生成信号
                current_balance = order_manager._get_account_balance()
                signal = generate_signal(df, symbol, current_balance, order_manager.trade_history)
                
                # 发送信号分析（如果有信号）
                if signal:
                    send_signal_analysis_telegram(symbol, signal)
                    
                    # 执行交易
                    execution_result = order_manager.execute_order(signal)
                    
                    # 发送交易执行结果
                    send_trade_execution_telegram(symbol, execution_result, signal)
                    
                    if execution_result and execution_result.get('success'):
                        daily_trade_count += 1
                        time.sleep(60)  # 交易后暂停1分钟
            
            # 定期保存系统状态
            if time.time() - last_save_time > CONFIG['RECOVERY_SAVE_INTERVAL']:
                save_recovery_state(order_manager)
                last_save_time = time.time()
            
            # 休眠到下个周期
            time.sleep(300)  # 5分钟检查一次
            
        except KeyboardInterrupt:
            logger.info("收到停止信号，正在安全退出...")
            save_recovery_state(order_manager)  # 退出前保存状态
            send_telegram("🛑 交易机器人已停止")
            break
        except Exception as e:
            logger.error(f"主循环异常: {str(e)}")
            send_telegram(f"❌ 系统异常: {str(e)}")
            save_recovery_state(order_manager)  # 异常时保存状态
            time.sleep(60)

if __name__ == "__main__":
    # 环境检查
    print("🔧 交易机器人 v1.0")
    print("=" * 50)
    
    # 显示配置信息
    print(f"交易类型: {'期货' if CONFIG['TRADING_TYPE'] == 'futures' else '现货'}")
    print(f"杠杆: {CONFIG['LEVERAGE']}x" if CONFIG['TRADING_TYPE'] == 'futures' else "杠杆: 无（现货交易）")
    print(f"风险比例: {CONFIG['RISK_PERCENT']*100:.2f}%")
    print(f"交易品种: {', '.join(TRADE_SYMBOLS.keys())}")
    print(f"测试模式: {'是' if CONFIG['TESTNET'] else '否'}")
    print("=" * 50)
    
    # 最终确认
    if not CONFIG['TESTNET']:
        # 检查是否在交互式环境中
        import sys
        if sys.stdin.isatty():
            confirm = input("⚠️  即将连接实盘交易，请确认 (输入 'YES' 继续): ")
            if confirm != 'YES':
                print("已取消启动")
                exit(0)
        else:
            # 非交互式环境，检查环境变量确认
            import os
            auto_confirm = os.getenv('XTRADER_CONFIRM_LIVE', 'false').lower()
            if auto_confirm != 'true':
                logger.error("⚠️ 实盘模式需要确认，但当前在非交互环境中")
                logger.error("请设置环境变量: export XTRADER_CONFIRM_LIVE=true")
                logger.error("或者修改config.json中的testnet设置为true")
                send_telegram("❌ 实盘模式启动失败：需要用户确认")
                exit(1)
            else:
                logger.warning("⚠️ 通过环境变量确认，即将启动实盘交易")
                send_telegram("⚠️ 实盘交易模式已启动")
    
    main()
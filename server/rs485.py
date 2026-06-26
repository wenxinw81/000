# websocket_server_simple.py
import asyncio
import websockets
import json
from typing import Set
import signal
import sys
import threading
import time


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RS485串口通信脚本
功能：
1. 支持十六进制指令的发送和接收
2. 自动断线重连机制
3. 异常处理和日志记录
4. 支持多种数据格式
"""

import serial
import serial.tools.list_ports
import logging
import queue
from datetime import datetime
from typing import Optional, List, Union, Tuple
import os
import sys
from pathlib import Path
from license_core import get_machine_code, load_license, verify_license_code

global Comm485
global server

Comm485=None
server=None

def enforce_license_or_exit():
    current_dir = os.getcwd()
    result = verify_license_code(get_machine_code(), load_license(Path(current_dir)))
    if not result.ok:
        print("=" * 60)
        print("软件未授权，rs485 服务已拒绝启动。")
        print(f"原因: {result.message}")
        print(f"本机机器码: {get_machine_code()}")
        print("请通过注册窗口完成授权后再启动。")
        print("=" * 60)
        sys.exit(3)

enforce_license_or_exit()

class RS485Communicator:
    """RS485串口通信类"""
    
    def __init__(self, 
                 port: str = 'COM4',
                 baudrate: int = 9600,
                 bytesize: int = 8,
                 parity: str = 'N',
                 stopbits: int = 1,
                 timeout: float = 1.0,
                 write_timeout: float = 1.0,
                 retry_interval: float = 3.0,
                 max_retries: int = 10):
        """
        初始化RS485通信器
        
        Args:
            port: 串口端口，如 'COM4'
            baudrate: 波特率，默认9600
            bytesize: 数据位，默认8
            parity: 校验位，'N'为无校验，'E'为偶校验，'O'为奇校验
            stopbits: 停止位，1或2
            timeout: 读取超时时间(秒)
            write_timeout: 写入超时时间(秒)
            retry_interval: 重连间隔(秒)
            max_retries: 最大重连次数
        """
        # 串口参数
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.write_timeout = write_timeout
        
        # 重连参数
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.current_retries = 0
        
        # 串口对象
        self.ser: Optional[serial.Serial] = None
        self.is_connected = False
        self.last_connect_time = None
        
        # 线程控制
        self.reconnect_thread: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.send_queue = queue.Queue()
        self.receive_queue = queue.Queue()
        self.running = False
        
        # 日志设置
        self.setup_logging()
        
        # 数据统计
        self.stats = {
            'bytes_sent': 0,
            'bytes_received': 0,
            'commands_sent': 0,
            'commands_received': 0,
            'reconnect_count': 0,
            'errors': 0
        }
    
    def setup_logging(self):
        """配置日志系统"""
        # 创建logs目录
        if not os.path.exists('logs'):
            os.makedirs('logs')
        
        # 日志文件名包含日期
        log_filename = f'logs/rs485_{datetime.now().strftime("%Y%m%d")}.log'
        
        # 配置logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger('RS485')
    
    def get_serial_parity(self) -> str:
        """将校验位字符串转换为serial库的常量"""
        parity_map = {
            'N': serial.PARITY_NONE,
            'E': serial.PARITY_EVEN,
            'O': serial.PARITY_ODD,
            'M': serial.PARITY_MARK,
            'S': serial.PARITY_SPACE
        }
        return parity_map.get(self.parity.upper(), serial.PARITY_NONE)
    
    def get_serial_stopbits(self) -> float:
        """将停止位转换为serial库的常量"""
        if self.stopbits == 1:
            return serial.STOPBITS_ONE
        elif self.stopbits == 2:
            return serial.STOPBITS_TWO
        else:
            return serial.STOPBITS_ONE_POINT_FIVE
    
    def get_serial_bytesize(self) -> int:
        """将数据位转换为serial库的常量"""
        bytesize_map = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS
        }
        return bytesize_map.get(self.bytesize, serial.EIGHTBITS)
    
    def hex_string_to_bytes(self, hex_str: str) -> bytes:
        """
        将十六进制字符串转换为字节
        
        Args:
            hex_str: 十六进制字符串，如 "01 02 03" 或 "010203" 或 "0x01 0x02"
            
        Returns:
            字节数据
        """
        # 移除所有空格和0x前缀
        hex_str = hex_str.replace(' ', '').replace('0x', '').replace(',', '')
        
        # 检查是否为有效的十六进制字符串
        if not all(c in '0123456789ABCDEFabcdef' for c in hex_str):
            raise ValueError(f"无效的十六进制字符串: {hex_str}")
        
        # 如果长度是奇数，在前面补0
        if len(hex_str) % 2 != 0:
            hex_str = '0' + hex_str
        
        try:
            return bytes.fromhex(hex_str)
        except ValueError as e:
            self.logger.error(f"十六进制转换失败: {e}")
            raise
    
    def bytes_to_hex_string(self, data: bytes, separator: str = ' ') -> str:
        """
        将字节数据转换为十六进制字符串
        
        Args:
            data: 字节数据
            separator: 分隔符，默认为空格
            
        Returns:
            十六进制字符串
        """
        return separator.join(f'{b:02X}' for b in data)
    
    def connect(self) -> bool:
        """连接串口"""
        try:
            self.logger.info(f"尝试连接串口 {self.port}...")
            
            # 检查端口是否存在
            available_ports = [port.device for port in serial.tools.list_ports.comports()]
            if self.port not in available_ports:
                self.logger.warning(f"端口 {self.port} 不存在，可用端口: {available_ports}")
                # 尝试自动查找可能的端口
                for port in available_ports:
                    if 'COM' in port or 'ttyUSB' in port or 'ttyACM' in port:
                        self.logger.info(f"尝试使用 {port} 替代 {self.port}")
                        self.port = port
                        break
            
            # 创建串口连接
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.get_serial_bytesize(),
                parity=self.get_serial_parity(),
                stopbits=self.get_serial_stopbits(),
                timeout=self.timeout,
                write_timeout=self.write_timeout
            )
            
            # 设置RS485相关参数（如果硬件支持）
            try:
                # 一些串口芯片支持RS485模式设置
                self.ser.rs485_mode = serial.rs485.RS485Settings()
                self.logger.info("已启用RS485模式")
            except:
                self.logger.info("使用标准串口模式（部分硬件需要外部RS485转换器）")
            
            # 清空缓冲区
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            
            self.is_connected = True
            self.last_connect_time = datetime.now()
            self.current_retries = 0
            self.stats['reconnect_count'] += 1
            
            self.logger.info(f"串口连接成功: {self.port}, 波特率: {self.baudrate}")
            self.print_connection_info()
            
            return True
            
        except serial.SerialException as e:
            self.logger.error(f"连接串口失败: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            self.logger.error(f"连接过程中发生未知错误: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """断开串口连接"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                self.logger.info("串口已关闭")
            except Exception as e:
                self.logger.error(f"关闭串口时出错: {e}")
        
        self.is_connected = False
        self.ser = None
    
    def print_connection_info(self):
        """打印连接信息"""
        if self.ser:
            info = f"""
            连接信息:
            端口: {self.ser.port}
            波特率: {self.ser.baudrate}
            数据位: {self.ser.bytesize}
            校验位: {self.ser.parity}
            停止位: {self.ser.stopbits}
            超时: {self.ser.timeout}
            写入超时: {self.ser.write_timeout}
            """
            self.logger.info(info)
    
    def send_data(self, data: Union[str, bytes, List[int]]) -> bool:
        """
        发送数据
        
        Args:
            data: 可以是十六进制字符串、字节数据或整数列表
            
        Returns:
            发送是否成功
        """
        if not self.is_connected or not self.ser or not self.ser.is_open:
            self.logger.warning("串口未连接，无法发送数据")
            return False
        
        try:
            # 转换数据为字节
            if isinstance(data, str):
                # 十六进制字符串
                # byte_data = self.hex_string_to_bytes(data)
                byte_data=data.encode('utf-8')
            elif isinstance(data, bytes):
                # 字节数据
                byte_data = data
            elif isinstance(data, list):
                # 整数列表
                byte_data = bytes(data)
            else:
                raise ValueError(f"不支持的数据类型: {type(data)}")

            # 发送数据
            bytes_written = self.ser.write(byte_data)
            self.ser.flush()  # 等待所有数据发送完成
            
            # 更新统计
            self.stats['bytes_sent'] += bytes_written
            self.stats['commands_sent'] += 1
            
            hex_str = self.bytes_to_hex_string(byte_data)
            self.logger.info(f"发送数据 ({bytes_written} 字节): {hex_str}")
            
            return True
            
        except serial.SerialTimeoutException:
            self.logger.error("发送数据超时")
            self.stats['errors'] += 1
            return False
        except serial.SerialException as e:
            self.logger.error(f"发送数据时串口错误: {e}")
            self.is_connected = False
            self.stats['errors'] += 1
            return False
        except Exception as e:
            self.logger.error(f"发送数据时发生未知错误: {e}")
            self.stats['errors'] += 1
            return False
    
    def receive_data(self, expected_length: int = 0, timeout: float = None) -> Optional[bytes]:
        """
        接收数据
        
        Args:
            expected_length: 期望接收的数据长度，0表示读取所有可用数据
            timeout: 读取超时时间，None表示使用默认超时
            
        Returns:
            接收到的字节数据，失败返回None
        """
        if not self.is_connected or not self.ser or not self.ser.is_open:
            self.logger.warning("串口未连接，无法接收数据")
            time.sleep(2)
            return None
        
        try:
            # 设置临时超时
            original_timeout = self.ser.timeout
            if timeout is not None:
                self.ser.timeout = timeout
            
            if expected_length > 0:
                # 读取指定长度的数据
                data = self.ser.read(expected_length)
            else:
                # 读取所有可用数据
                data = self.ser.read(self.ser.in_waiting or 1)
            
            # 恢复原始超时
            if timeout is not None:
                self.ser.timeout = original_timeout
            
            if data:
                # 更新统计
                self.stats['bytes_received'] += len(data)
                self.stats['commands_received'] += 1
                
                hex_str = self.bytes_to_hex_string(data)
                self.logger.info(f"接收数据 ({len(data)} 字节): {hex_str}")

                decoded_data = data.decode('utf-8', errors='ignore')
                self.logger.info(f"接收到数据: {decoded_data}")
            
            return data if data else None
            
        except serial.SerialException as e:
            self.logger.error(f"接收数据时串口错误: {e}")
            self.is_connected = False
            self.stats['errors'] += 1
            return None
        except Exception as e:
            self.logger.error(f"接收数据时发生未知错误: {e}")
            self.stats['errors'] += 1
            return None
    
    def send_and_receive(self, 
                        send_data: Union[str, bytes, List[int]], 
                        expected_length: int = 0,
                        receive_timeout: float = 2.0,
                        delay_before_receive: float = 0.1) -> Optional[bytes]:
        """
        发送数据并接收响应
        
        Args:
            send_data: 要发送的数据
            expected_length: 期望接收的数据长度
            receive_timeout: 接收超时时间
            delay_before_receive: 发送后延迟接收的时间
            
        Returns:
            接收到的数据
        """
        # 发送数据
        if not self.send_data(send_data):
            return None
        
        # 等待设备响应
        time.sleep(delay_before_receive)
        
        # 接收数据
        return self.receive_data(expected_length, receive_timeout)
    
    def send(self, 
                        send_data: Union[str, bytes, List[int]]
                        ) -> Optional[bytes]:
        """
        发送数据并接收响应
        
        Args:
            send_data: 要发送的数据
            expected_length: 期望接收的数据长度
            receive_timeout: 接收超时时间
            delay_before_receive: 发送后延迟接收的时间
            
        Returns:
            接收到的数据
        """
        # 发送数据
        if not self.send_data(send_data):
            return False
        
        # 接收数据
        return True
    
    def auto_reconnect_monitor(self):
        """自动重连监控线程"""
        self.logger.info("自动重连监控线程启动")
        
        while self.running:
            try:
                if not self.is_connected or not self.ser or not self.ser.is_open:
                    self.logger.warning("检测到连接断开，尝试重连...")
                    
                    # 断开旧连接
                    self.disconnect()
                    
                    # 尝试重连
                    success = False
                    for attempt in range(self.max_retries):
                        if not self.running:
                            break
                        
                        self.logger.info(f"重连尝试 {attempt + 1}/{self.max_retries}")
                        if self.connect():
                            success = True
                            break
                        
                        # 等待后重试
                        if attempt < self.max_retries - 1:
                            time.sleep(self.retry_interval)
                    
                    if not success:
                        self.logger.error(f"重连失败，已达到最大重试次数 {self.max_retries}")
                
                # 定期检查连接状态
                time.sleep(1)  # 每秒检查一次
                
            except Exception as e:
                self.logger.error(f"重连监控线程错误: {e}")
                time.sleep(self.retry_interval)
        
        self.logger.info("自动重连监控线程停止")
    
    def start(self):
        """启动通信器"""
        if self.running:
            self.logger.warning("通信器已在运行中")
            return
        
        self.running = True
        
        # 初始连接
        if not self.connect():
            self.logger.warning("初始连接失败，重连监控将尝试自动连接")
        
        # 启动重连监控线程
        self.monitor_thread = threading.Thread(
            target=self.auto_reconnect_monitor,
            name="ReconnectMonitor",
            daemon=True
        )
        self.monitor_thread.start()
        
        self.logger.info("RS485通信器已启动")
    
    def stop(self):
        """停止通信器"""
        self.logger.info("正在停止RS485通信器...")
        self.running = False
        
        # 等待监控线程结束
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        
        # 断开连接
        self.disconnect()
        
        self.logger.info("RS485通信器已停止")
    
    def get_stats(self) -> dict:
        """获取通信统计信息"""
        uptime = 0
        if self.last_connect_time and self.is_connected:
            uptime = (datetime.now() - self.last_connect_time).total_seconds()
        
        stats = self.stats.copy()
        stats.update({
            'is_connected': self.is_connected,
            'uptime_seconds': uptime,
            'port': self.port,
            'baudrate': self.baudrate
        })
        
        return stats
    
    def print_stats(self):
        """打印统计信息"""
        stats = self.get_stats()
        
        print("\n" + "="*50)
        print("RS485通信统计信息")
        print("="*50)
        print(f"连接状态: {'已连接' if stats['is_connected'] else '未连接'}")
        print(f"串口端口: {stats['port']}")
        print(f"波特率: {stats['baudrate']}")
        print(f"运行时间: {stats['uptime_seconds']:.1f} 秒")
        print(f"发送字节数: {stats['bytes_sent']}")
        print(f"接收字节数: {stats['bytes_received']}")
        print(f"发送指令数: {stats['commands_sent']}")
        print(f"接收指令数: {stats['commands_received']}")
        print(f"重连次数: {stats['reconnect_count']}")
        print(f"错误次数: {stats['errors']}")
        print("="*50)

def test_modbus_commands(comm: RS485Communicator):
    """测试Modbus RTU常用指令"""
    
    # 示例Modbus RTU指令（需要根据实际设备修改）
    test_commands = [
        # 读取保持寄存器 (功能码 0x03)
        "01 03 00 00 00 01 84 0A",  # 从设备1读取寄存器0000-0000
        
        # 读取输入寄存器 (功能码 0x04)
        "01 04 00 00 00 01 31 CA",
        
        # 写单个寄存器 (功能码 0x06)
        "01 06 00 01 00 0A 18 1B",  # 向设备1的寄存器0001写入0x000A
        
        # 写多个寄存器 (功能码 0x10)
        "01 10 00 00 00 02 04 00 0A 00 0B 2B 9C",
    ]
    
    print("\n开始测试Modbus RTU指令...")
    
    for i, cmd in enumerate(test_commands, 1):
        print(f"\n测试指令 {i}: {cmd}")
        
        try:
            response = comm.send_and_receive(
                send_data=cmd,
                expected_length=8,  # 典型的Modbus响应长度
                receive_timeout=1.0,
                delay_before_receive=0.2
            )
            
            if response:
                hex_response = comm.bytes_to_hex_string(response)
                print(f"设备响应: {hex_response}")
            else:
                print("未收到响应")
                
        except Exception as e:
            print(f"测试过程中出错: {e}")
        
        time.sleep(0.5)  # 指令间延迟

def receive_data():
     global Comm485
     global server
     while True:
        try:
            if not (Comm485 is None or server is None):
                data = Comm485.receive_data(8, timeout=2.0)
                if data:
                    hex_data = Comm485.bytes_to_hex_string(data)
                    decoded_data = data.decode('utf-8', errors='ignore')
                    asyncio.run(server.sendmsg(decoded_data))
                    print(f"接收数据 ({len(data)} 字节): {decoded_data}")
                #else:
                    #print("未收到数据")
                    #asyncio.run(server.sendmsg("GGGGK002"))
        except Exception as e:
            time.sleep(2)
            print("接收失败",e)

#接收数据线程   
receivethread = threading.Thread(target=receive_data,daemon=True)
receivethread.start()

# def sendMsg():
#     global Comm485
#     while True:
#         time.sleep(2) #每秒一次心跳
#         try:
#             # 异步发送
#             Comm485.send("GGGGK002")
#         except Exception as e:
#             print("发送失败",e)
        
# mythread = threading.Thread(target=sendMsg,daemon=True)
# mythread.start()

def interactive_mode(comm: RS485Communicator):
    """交互式命令行模式"""
    print("\n进入RS485串口通信交互模式")
    print("可用命令:")
    print("  send <hex>    - 发送十六进制指令，如: send 01 03 00 00 00 01")
    print("  recv [len]    - 接收数据，可指定长度")
    print("  stats         - 显示统计信息")
    print("  test          - 运行测试指令")
    print("  ports         - 查看可用串口")
    print("  info          - 显示连接信息")
    print("  clear         - 清屏")
    print("  exit          - 退出程序")
    
    while True:
        try:
            cmd_input = input("\nRS485> ").strip()
            
            if not cmd_input:
                continue
            
            parts = cmd_input.split()
            command = parts[0].lower()
            
            if command == 'exit':
                print("正在退出...")
                break
            
            elif command == 'send' and len(parts) > 1:
                hex_data = ' '.join(parts[1:])
                try:
                    response = comm.send_and_receive(
                        send_data=hex_data,
                        receive_timeout=2.0,
                        delay_before_receive=0.1
                    )
                    
                    if response:
                        hex_response = comm.bytes_to_hex_string(response)
                        print(f"发送: {hex_data}")
                        print(f"接收: {hex_response}")
                    else:
                        print("未收到响应")
                        
                except Exception as e:
                    print(f"发送失败: {e}")
            
            elif command == 'recv':
                expected_len = int(parts[1]) if len(parts) > 1 else 0
                data = comm.receive_data(expected_len, timeout=2.0)
                
                if data:
                    hex_data = comm.bytes_to_hex_string(data)
                    print(f"接收数据 ({len(data)} 字节): {hex_data}")
                else:
                    print("未收到数据")
            
            elif command == 'stats':
                comm.print_stats()
            
            elif command == 'test':
                test_modbus_commands(comm)
            
            elif command == 'ports':
                ports = serial.tools.list_ports.comports()
                print(f"可用串口 ({len(ports)} 个):")
                for port in ports:
                    print(f"  {port.device}: {port.description}")
            
            elif command == 'info':
                comm.print_connection_info()
            
            elif command == 'clear':
                os.system('cls' if os.name == 'nt' else 'clear')
            
            else:
                print(f"未知命令: {command}")
                
        except KeyboardInterrupt:
            print("\n检测到Ctrl+C，正在退出...")
            break
        except Exception as e:
            print(f"命令执行出错: {e}")

def main():
    """主函数"""
    print("="*60)
    print("RS485串口通信工具")
    print("="*60)
    
    # 检测可用端口
    ports = serial.tools.list_ports.comports()
    print(f"检测到 {len(ports)} 个可用串口:")
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port.device}: {port.description}")
    
    # 配置参数（可根据需要修改）
    config = {
        'port': '/dev/ttyUSB0',
        'baudrate': 9600,
        'bytesize': 8,
        'parity': 'N',
        'stopbits': 1,
        'timeout': 1.0,
        'retry_interval': 3.0,
        'max_retries': 5
    }
    
    # 创建通信器实例
    comm = RS485Communicator(**config)
    global Comm485
    Comm485=comm
    
    try:
        # 启动通信器
        comm.start()
        
        # 等待连接建立
        time.sleep(1)
        
        # 显示统计信息
        comm.print_stats()
        
        # 进入交互模式
        # interactive_mode(comm)
        
    except KeyboardInterrupt:
        comm.stop()
        global server
        if not (server is None):
            server.shutdown()
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")
        import traceback
        traceback.print_exc()
    # finally:
    #     # 确保资源被正确释放
    #     # comm.stop()
    #     print("\n程序已安全退出")

class WebSocketServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.is_running = False
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """处理终止信号"""
        print("\n正在关闭服务器...")
        self.is_running = False
        asyncio.run(self.shutdown())
    
    async def shutdown(self):
        """关闭所有连接"""
        for ws in list(self.clients):
            await ws.close()
        sys.exit(0)
    
    async def heartbeat(self, ws):
        """发送心跳包"""
        try:
            await ws.send(json.dumps({"type": "ping"}))
        except:
            pass

    #发送广播给所有客户端
    async def sendmsg(self,msg):
        # 发送指令
        for client in self.clients:
            try:
                await client.send(json.dumps({
                    "type": "broadcast",
                    "from": "server",
                    "message": msg
                }))
                print("已发送",msg)
            except Exception as e:
                print("发送广播消息失败",e)

    async def handler(self, ws):
        """处理WebSocket连接"""
        self.clients.add(ws)
        client_id = f"client-{len(self.clients)}"
        print(f"客户端连接: {client_id}")
        
        try:
            # 发送连接确认
            await ws.send(json.dumps({
                "type": "connected",
                "client_id": client_id,
                "message": "连接成功"
            }))
            
            # 处理消息
            async for message in ws:
                try:
                    data = json.loads(message)
                    print(f"收到: {data}")
                    
                    # 处理指令
                    if data.get("type") == "command":
                        cmd = data.get("command", "")
                        if cmd == "ping":
                            await ws.send(json.dumps({
                                "type": "pong",
                                "timestamp": data.get("timestamp")
                            }))
                        elif cmd == "broadcast":
                            # 广播消息给所有客户端
                            msg = data.get("message", "")
                            for client in self.clients:
                                if client != ws:
                                    await client.send(json.dumps({
                                        "type": "broadcast",
                                        "from": client_id,
                                        "message": msg
                                    }))
                        else:
                            global Comm485
                            try:
                                # 发送命令给串口
                                Comm485.send(cmd)
                            except Exception as e:
                                print("发送串口指令失败",e)
                            # 默认回显
                            await ws.send(json.dumps({
                                "type": "response",
                                "command": cmd,
                                "result": f"执行命令: {cmd}"
                            }))
                    else:
                        # 普通消息回显
                        await ws.send(json.dumps({
                            "type": "echo",
                            "message": f"收到: {data}"
                        }))
                        
                except json.JSONDecodeError:
                    # 文本消息
                    await ws.send(json.dumps({
                        "type": "echo",
                        "message": f"文本: {message}"
                    }))
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"客户端断开: {client_id}")
        finally:
            self.clients.remove(ws)
            print(f"剩余连接: {len(self.clients)}")
    
    async def auto_reconnect_server(self):
        """自动重启服务器"""
        while self.is_running:
            try:
                print(f"启动WebSocket服务器 ws://{self.host}:{self.port}")
                async with websockets.serve(self.handler, self.host, self.port) as server:
                    self.is_running = True
                    await server.wait_closed()
            except Exception as e:
                print(f"服务器异常: {e}, 5秒后重连...")
                await asyncio.sleep(5)
                continue
    
    def run(self):
        """运行服务器"""
        print("WebSocket服务器启动中...")
        self.is_running = True
        asyncio.run(self.auto_reconnect_server())

# def sendImage():
#      global server
#      while True:
#         time.sleep(2) #每秒一次心跳
#         # 异步发送
#         asyncio.run(server.sendmsg("GGGGK002"))
        
# mythread = threading.Thread(target=sendImage,daemon=True)
# mythread.start()

# 安装依赖: pip install websockets

if __name__ == "__main__":
    main()
    server = WebSocketServer(host="0.0.0.0", port=5007)
    server.run()

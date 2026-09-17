# 炼丹台 Training Monitor 使用帮助

本手册覆盖当前仓库的电脑端像素面板、SSH 直连采集、可选服务器端服务、手机同步、安全设置和故障排查。

仓库地址：https://github.com/Zephyer969/training-monitor

## 1. 推荐架构

~~~text
训练服务器  --SSH只读采集-->  本地电脑像素面板  --局域网/VPN/HTTPS-->  手机 App
~~~

电脑端负责读取 GPU、训练进程、日志、Loss 和 mIoU；手机只读取电脑端快照，不直接访问训练服务器，也不保存服务器 SSH 密码。

日常查看推荐使用 SSH 直连模式。它不要求训练服务器安装本项目、不要求开放监控 API 端口，也不要求手工建立隧道。

## 2. 最快启动

### 2.1 本地 Windows 安装

以下命令在本地 PowerShell 执行，不要在服务器 SSH 终端执行。

~~~powershell
git clone https://github.com/Zephyer969/training-monitor.git
cd training-monitor
py -3 -m pip install -e ".[desktop]"
py -3 -m monitorctl_py fix-path
~~~

关闭当前 PowerShell，再打开一个新的 PowerShell，让 PATH 生效。检查：

~~~powershell
py -3 --version
ssh -V
py -3 -c "import tkinter; print('Tk OK')"
Get-Command train_mot
~~~

Windows Python 一般自带 Tk；若导入 tkinter 失败，重新安装 Python 并保留 Tcl/Tk 组件。

### 2.2 先看演示界面

~~~powershell
py -3 -m monitorctl_py desktop --demo --gpus 4
~~~

演示数据是模拟数据，不代表真实服务器状态。

### 2.3 无公钥、密码模式启动

直接在本地 PowerShell 输入：

~~~powershell
start train_mot user@server
~~~

例如：

~~~powershell
start train_mot sys001@192.168.63.122
~~~

随后会打开连接窗口并显示系统 SSH 密码提示。输入密码时不会显示字符，这是正常现象。认证成功后，像素面板在本地打开。

密码不会保存到项目配置、命令参数、日志或服务器文件。start 会创建单独连接窗口，面板运行期间不要关闭它。需要在当前窗口查看错误时使用：

~~~powershell
train_mot user@server
~~~

### 2.4 命令必须在本地执行

下面的方式不能把 Windows GUI 带回本地：

~~~text
ssh user@server
start train_mot user@server
~~~

因为第二条命令是在服务器 Shell 中运行。正确方式是在本地 PowerShell/CMD 中直接运行：

~~~powershell
start train_mot user@server
~~~

### 2.5 第一次主机指纹确认

第一次连接新主机时，SSH 可能询问是否信任主机指纹。确认指纹来源可信后再输入 yes。不要使用 StrictHostKeyChecking=no，也不要关闭主机指纹检查。

## 3. SSH 公钥模式（可选）

密码模式已经可以使用。希望以后不输入服务器密码时，才需要配置公钥。

### 3.1 生成密钥

~~~powershell
ssh-keygen -t ed25519 -C "training-monitor"
~~~

常见文件：

~~~text
C:\Users\你的用户名\.ssh\id_ed25519
C:\Users\你的用户名\.ssh\id_ed25519.pub
~~~

.pub 是公钥，可以复制；没有扩展名的 id_ed25519 是私钥，只能留在本地，不能上传 GitHub 或发送给别人。

### 3.2 复制公钥

Windows 没有 ssh-copy-id 时执行：

~~~powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh user@server "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys"
~~~

这一步会要求输入一次服务器密码，只发送公钥，不发送私钥。测试：

~~~powershell
ssh user@server
~~~

也可以用 Windows SSH Agent：

~~~powershell
Get-Service ssh-agent
Start-Service ssh-agent
ssh-add $env:USERPROFILE\.ssh\id_ed25519
~~~

不要把私钥口令写入脚本。
+
## 4. 电脑端配置

### 4.1 一次性连接与保存配置

最不容易连错服务器的方式是每次显式指定：

~~~powershell
start train_mot user@server
~~~

想保存默认目标时复制模板：

~~~powershell
Copy-Item monitor.config.example.json monitor.config.json
~~~

编辑后的基本结构：

~~~json
{
  "ssh": "user@your-training-server",
  "remote_python": "auto",
  "interval": 2,
  "log_roots": [],
  "names_file": "monitor.names.json",
  "local_bind": "0.0.0.0",
  "local_port": 8765,
  "local_token": "",
  "local_token_file": "monitor.local.token",
  "cloudflare_enabled": false,
  "cloudflared_path": ""
}
~~~

字段说明：

| 字段 | 作用 | 建议 |
|---|---|---|
| ssh | SSH 别名或 user@host | 可填地址，绝不填密码 |
| remote_python | 服务器 Python | 默认 auto，尝试 python3、python |
| interval | 采集间隔，秒 | 2 或 3 |
| log_roots | 额外日志目录或文件 | 自动发现不到时填写 |
| names_file | 本地名称和隐藏状态 | 保留默认值 |
| local_bind | 手机接口监听地址 | 不需要手机时用 127.0.0.1 |
| local_port | 手机接口端口 | 默认 8765 |
| local_token | 手动 Token | 建议留空自动生成 |
| local_token_file | Token 文件 | 不要提交 |
| cloudflare_enabled | 是否启用隧道 | 需要外网时再开启 |
| cloudflared_path | cloudflared.exe 路径 | 已在 PATH 时留空 |

monitor.config.json 已加入 Git 忽略。显式执行 start train_mot user@server 时，该目标优先于旧配置，不会因旧配置静默连接到另一台服务器。

### 4.2 直接模块启动

~~~powershell
py -3 -m monitorctl_py desktop --ssh user@server
~~~

未安装包、直接从源码启动时：

~~~powershell
$env:PYTHONPATH = (Get-Location).Path + '\server'
py -3 -m monitorctl_py desktop --ssh user@server
~~~

### 4.3 双击启动

有配置文件时可以双击 start-monitor.vbs。需要看到 SSH 错误或密码提示时使用：

~~~powershell
start train_mot user@server
~~~

排错入口：

~~~text
start-monitor.cmd user@server
~~~

## 5. 常用启动参数

~~~powershell
# 基本启动
train_mot user@server

# 每 3 秒刷新
train_mot user@server --interval 3

# 指定服务器 Python
train_mot user@server --remote-python /opt/conda/bin/python

# 增加日志目录
train_mot user@server --log-root /data/project/work_dirs

# 指定本地名称文件
train_mot user@server --names-file D:\training-monitor\monitor.names.json

# 不启用手机同步
train_mot user@server --no-local-gateway

# 只监听本机
train_mot user@server --local-bind 127.0.0.1

# 修改手机同步端口
train_mot user@server --local-port 9876
~~~

查看完整参数：

~~~powershell
training-monitor desktop --help
~~~

## 6. 日志、GPU 和任务识别

SSH 直连会读取：

- nvidia-smi 的物理 GPU、显存、温度、功耗和 GPU 进程；
- 正在运行的训练 Python 进程；
- 进程命令中的 --work-dir 和配置路径；
- OpenMMLab、MMEngine、YOLO/Ultralytics 常见日志；
- 文本日志、JSONL 日志和 results.csv。

DDP 多进程会合并为一个任务；一个模型使用多张 GPU 时显示一个任务，并展示它实际占用的 GPU。

自动发现不到时追加目录：

~~~powershell
train_mot user@server --log-root /home/user/project/work_dirs
~~~

追加多个目录也可以写成一行：

~~~powershell
train_mot user@server --log-root /home/user/project1/work_dirs --log-root /home/user/project2/runs
~~~

服务器没有 python3 时：

~~~powershell
train_mot user@server --remote-python /home/user/miniconda3/envs/mmseg/bin/python
~~~

服务器至少需要 Python 3.8+、可读训练日志和 /proc；GPU 硬件信息需要 nvidia-smi。没有落盘日志、日志目录不在发现范围、指标名称完全自定义时，可能需要手工指定目录或适配解析器。

## 7. 电脑端面板操作

面板包含：

- 任务表：名称、状态、Step、Epoch、Loss、mIoU、GPU 和进度；
- Loss 与 mIoU 两条独立曲线，固定并列显示；
- 导师主炼丹动作：搅拌棒从丹炉左侧经过中央到右侧；
- 每张 GPU 独立显示使用率、显存、温度、功耗和助手；
- GPU 数量和任务数量自动适配；
- 训练中任务排前，已完成任务靠后；
- 完成任务不会自动消失，点击红色像素 × 才会隐藏；
- F2 / 重命名可将相近实验标为 unit1、unit2；
- Ctrl + 鼠标滚轮等比例缩放，Ctrl + 0 恢复默认，Ctrl + + / Ctrl + - 微调。

名称和隐藏状态只保存在本地 monitor.names.json，不会改动服务器日志或训练进程。
+
## 8. 手机同步

### 8.1 安装 App

从 Release 下载最新 APK：

https://github.com/Zephyer969/training-monitor/releases/latest

Android 阻止安装时，在系统设置中允许当前浏览器或文件管理器安装未知来源应用。

### 8.2 同一局域网

1. 打开电脑面板；
2. 点击“手机同步”；
3. 把电脑地址和本地 Token 填入 App；
4. 手机和电脑保持同一 Wi-Fi。

地址示例：

~~~text
http://192.168.1.20:8765
~~~

不要填写 127.0.0.1、训练服务器地址、服务器 API Token 或 SSH 密码。127.0.0.1 在手机上代表手机自己。

同一 Wi-Fi 无法访问时，只允许 Windows 防火墙的专用网络 8765/TCP 入站，不要直接开放公网端口。

### 8.3 Tailscale/WireGuard

电脑和手机加入同一个私有 VPN 后，使用电脑 VPN 地址：

~~~text
http://100.100.12.8:8765
~~~

手机仍只访问电脑，电脑再访问训练服务器。

### 8.4 Cloudflare Quick Tunnel

Windows 流程：

1. 双击 install-cloudflared.cmd；
2. 重新打开项目目录；
3. 双击 start-monitor-cloudflare.vbs；
4. 等待“手机同步 ✓”；
5. 把 https://...trycloudflare.com 地址和 Token 填入 App。

Quick Tunnel 地址重启后可能变化，适合个人实验和临时查看。Cloudflare 模式把同步中继固定到 127.0.0.1:8765，手机必须使用 HTTPS 隧道地址。

### 8.5 Token

默认 Token 保存在 monitor.local.token。建议 local_token 留空，让项目自动生成。怀疑泄露时，在电脑端“手机同步”中点击“重置 Token”，再把新 Token 填入 App。接口是只读的，不支持控制训练或修改服务器。

## 9. 可选：服务器端 API 模式

SSH 直连不需要服务器安装本项目。需要服务器 API 或传统 Token 时才安装：

~~~bash
curl -fL https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-install-server.sh | bash
~~~

建议先查看脚本再执行，不要直接执行不信任的镜像脚本。也可以：

~~~bash
python3 -m pip install --upgrade https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-server.tar.gz
~~~

检查、启动和维护：

~~~bash
training-monitor doctor
training-monitor setup
training-monitor start
training-monitor status
training-monitor connection
training-monitor restart
training-monitor logs
training-monitor stop
training-monitor rotate-token
~~~

配置示例：

~~~bash
training-monitor config show
training-monitor config set LOG_ROOTS "/home/user/project/work_dirs /home/user/runs"
training-monitor config set PORT 6006
training-monitor restart
~~~

服务器 API Token 和电脑手机同步 Token 是两套 Token。手机 App 应填写电脑“手机同步”弹窗里的本地 Token。

## 10. 安全注意事项

### 10.1 SSH

- 没有公钥时由系统 OpenSSH 提示输入密码；
- 项目不保存 SSH 密码；
- 不要把密码写入配置、脚本、Shell 历史或 README；
- 私钥不上传 GitHub；
- 第一次连接核对主机指纹；
- 训练服务器使用权限尽可能小的专用账号。

### 10.2 直连模式边界

电脑端通过 SSH 执行内存中的采集代码，读取 GPU、进程和日志。项目不会在训练服务器安装监控文件、创建监控 API 或写入项目缓存。

SSH 仍可能被服务器系统审计日志记录，这是正常安全策略，项目不能也不应绕过。训练账号必须有读取相关进程和日志的权限。

### 10.3 手机接口

- 本地同步接口必须使用 Token；
- App 只读取电脑快照；
- 不要把 8765 端口直接暴露到公网；
- 局域网使用专用网络防火墙；
- 外网优先使用 VPN 或 Cloudflare HTTPS；
- 不要把数据集隐私、账号密码或 SSH 凭据写进训练日志；
- Token 泄露后立即重置。

以下本地文件不应提交：

~~~text
monitor.config.json
monitor.names.json
monitor.local.token
server/state.json
token.txt
~~~

提交前检查：

~~~powershell
git status --short
git diff -- monitor.config.json monitor.local.token
~~~

## 11. 常见问题

### 11.1 找不到 train_mot

~~~powershell
py -3 -m pip install -e ".[desktop]"
py -3 -m monitorctl_py fix-path
~~~

关闭并重新打开终端，再执行：

~~~powershell
Get-Command train_mot
~~~

仍失败时：

~~~powershell
py -3 -m monitorctl_py desktop --ssh user@server
~~~

### 11.2 看不到密码提示

使用可见终端：

~~~powershell
train_mot user@server
~~~

密码模式下不要使用隐藏窗口的 start-monitor.vbs。

### 11.3 SSH 认证失败

Permission denied (publickey,password) 表示 SSH 认证失败，不是日志解析错误。检查用户名、地址、密码、服务器密码登录策略，并先测试：

~~~powershell
ssh user@server
~~~

Connection timed out 或 Connection refused 时检查本地网络、服务器 SSH 服务、防火墙、安全组和地址。

### 11.4 没有训练任务

检查训练是否运行、SSH 用户是否能读日志、服务器是否有 nvidia-smi，并补充：

~~~powershell
train_mot user@server --log-root /home/user/project/work_dirs --remote-python /opt/conda/bin/python
~~~

### 11.5 GUI 依赖错误

~~~powershell
py -3 -m pip install -e ".[desktop]"
py -3 -c "from PIL import Image; import tkinter; print('desktop dependencies OK')"
~~~

### 11.6 手机 HTTP 401

重新打开电脑“手机同步”复制 Token，确认地址是电脑地址而不是服务器地址，必要时重置 Token。

### 11.7 手机 HTTP 530

确认面板和 cloudflared 都在运行，重新启动 start-monitor-cloudflare.vbs 获取新的 HTTPS 地址。Quick Tunnel 重启后地址可能变化。

### 11.8 手机能打开但不更新

电脑端 SSH 采集可能断开。查看面板错误提示并重新启动：

~~~powershell
train_mot user@server
~~~

手机可能仍显示上一次快照，但断线后不会产生新的数据。
+
## 12. 更新、停止和卸载

### 12.1 更新本地

~~~powershell
git pull
py -3 -m pip install -e ".[desktop]"
py -3 -m monitorctl_py fix-path
~~~

不要提交本地配置、名称和 Token 文件。

### 12.2 更新服务器

~~~bash
curl -fL https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-install-server.sh | bash
training-monitor restart
~~~

### 12.3 停止

关闭电脑像素窗口即可，SSH 采集连接和本地手机同步接口会停止。

### 12.4 卸载本地包

~~~powershell
py -3 -m pip uninstall xunji-training-monitor
~~~

若仍能找到 train_mot，删除当前用户 Python Scripts 目录中的 train_mot.cmd，或从用户 PATH 移除对应目录。不要误删其他 Python 工具。

### 12.5 卸载服务器服务

先停止：

~~~bash
training-monitor stop
~~~

确认不再需要历史状态、Token 和日志后，再删除实际目录，例如：

~~~bash
rm -rf /root/autodl-tmp/training-monitor
rm -rf ~/.training-monitor
~~~

删除前必须确认路径，不要改成 /、/root 或其他不明确目录。

## 13. 命令速查

| 场景 | 命令 |
|---|---|
| 安装电脑端 | py -3 -m pip install -e ".[desktop]" |
| 配置启动入口 | py -3 -m monitorctl_py fix-path |
| 演示界面 | py -3 -m monitorctl_py desktop --demo --gpus 4 |
| 密码模式启动 | start train_mot user@server |
| 当前窗口启动 | train_mot user@server |
| 直接模块启动 | py -3 -m monitorctl_py desktop --ssh user@server |
| 查看桌面参数 | training-monitor desktop --help |
| 服务器诊断 | training-monitor doctor |
| 服务器启动 | training-monitor start |
| 服务器状态 | training-monitor status |
| 服务器连接信息 | training-monitor connection |
| 服务器日志 | training-monitor logs |
| 服务器重启 | training-monitor restart |
| 服务器停止 | training-monitor stop |
| 重置服务器 API Token | training-monitor rotate-token |

## 14. 边界总结

- 主导师在所有 GPU 布局中只出现一次，每张 GPU 有独立助手；
- GPU 数量、GPU 状态和任务数量从服务器实时发现；
- Loss 和 mIoU 是两个独立曲线，没有 mIoU 时显示等待；
- 训练结束任务不会自动消失，必须手动点击红色像素 ×；
- 名称修改只影响本地面板，不写回服务器日志；
- 手机只读取电脑快照，不直接访问训练服务器；
- SSH 密码不保存，公钥私钥不进入项目；
- 电脑端直连不要求服务器安装监控程序；
- 公开网络访问必须使用 Token，并优先使用 VPN 或 HTTPS 隧道；
- 本项目用于个人训练状态查看，不替代服务器账号、SSH、网络边界和数据脱敏策略。

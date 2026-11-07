# 灵珑系统 · Linux 内核版

一套可独立启动的 aarch64 操作系统：Linux 7.3.0-rc7 内核 + 自研 init(PID 1) + BusyBox 用户态，Live ISO 启动后屏幕(tty1)与串口(ttyAMA0)各有一个 shell。ISO 内置 install-loongos，可把纯自研 LoongOS 写入硬盘。

> 本仓库由 NAS 归档包整理发布。已剥离运行时数据、密钥、审计日志与大型二进制镜像；
> 文档中的真实口令与内网 IP 已脱敏。镜像请用仓库内构建脚本生成，或从 Releases 获取。

## 目录结构

```
├── 本体/
├── 本体/LINGLONG_TODO.md
├── 本体/LINGLUM_TODO.md
├── 本体/build.sh
├── 本体/cleanup_qemu.sh
├── 本体/diag_grub.py
├── 本体/diag_mount.py
├── 本体/docs/
├── 本体/init
```

## 使用

请参考仓库内的说明文档与构建/部署脚本；首次运行前把示例地址、口令改成自己的值。

## 安全约定

- `data/`、`.env`、`env.*`、`*.pem`、`*.keystore`、`config.json`、`*.db`、`*.log` 均已在 `.gitignore` 中排除，切勿强制提交。
- 文档里的 `192.168.1.100` 与 `203.0.113.x` 是示例地址，`<REDACTED_PASSWORD>` 是脱敏占位符。
- 涉及管理后台的服务请只在可信局域网内使用。

## 许可证

MIT

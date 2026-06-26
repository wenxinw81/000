# Linux 授权版 app/rs485 构建包

这个仓库只用于 GitHub Actions 生成新的 Linux 可执行文件：

- `app`
- `rs485`

这两个文件源码内置授权校验，直接运行也会检查 `license.dat`。

## 使用方法

1. 把本目录所有内容上传到 GitHub 仓库根目录。
2. 打开 GitHub 仓库的 `Actions`。
3. 运行 `Build Linux Binaries`。
4. 构建成功后下载 artifact：`linux-authorized-binaries`。
5. 解压后得到：

```text
app
rs485
```

6. 把这两个文件覆盖到客户 Linux 端：

```text
python_RS485/app
python_RS485/rs485
```

7. 在 Linux 端执行：

```bash
chmod +x app rs485
./stop.sh
./start.sh
```

## 注意

- 不需要重新生成 Windows 注册机。
- 这个构建包不包含客户前端资源、数据库、上传文件。

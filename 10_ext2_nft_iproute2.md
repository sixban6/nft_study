# 扩展阶段二：nftables 与 iproute2 的梦幻联动 (黑魔法)

*类比 C 语言：跨模块全局变量、Hook 函数劫持。*

光有 `iproute2` 是不够的，因为 `iprule` 的匹配维度极度单一：它只能看源 IP、目标 IP 和少数基础特征。
如果我想实现：“封锁含有特定关键字的 HTTP 报文” 或 “凡是目标地为国外 IP，统一走 100 号路由表”，仅仅靠 `ip rule` 是完全做不到的。

这就需要 `nftables` 和 `iproute2` 双剑合璧。它们沟通的桥梁是一个看不见的幽灵：**Fwmark (防火墙标记)**。

---

## 1. Fwmark (防火墙标记：内核全局变量)

当一个数据包在 Linux 内核网卡栈中游走时，其实它是被装在一个叫做 `sk_buff`（Socket Buffer）的内存结构体里的。
这个结构体里有一块专属于这包的小内存空间，里面可以被写入一个数字叫 `skb->mark`，你可以理解为一个伴随整个数据包生命周期的**跨模块全局变量**。

**操作原理如下：**

1. 利用 `nftables` 极度强悍的报文拆解能力，抓取命中特征（如国外 IP 集、特定时间段、应用层协议）。
2. 在 `nftables` 中给这个特定的包的 `sk_buff` 黑板上偷偷写下一个标记，比如数字 `100`。
```bash
# nftables 语法：通过 meta mark 操作写入全局变量标志位
nft add rule inet mangle prerouting ip daddr @foreign_ips meta mark set 100
```
3. 包继续往前走进入了 `iproute2` 掌管的路由模块。这时候，`ip rule` 开始发挥威力了：
```bash
# iproute2 语法：这也就是所谓的策略路由分流本质
ip rule add fwmark 100 table 100
```
4. 于是，这个被 `nftables` 打上标的“可疑”包裹，乖乖抛弃了主路由表，跑去查阅神秘的 100 号私有路由表。

---

## 2. TPROXY 透明代理原理 (底层 Socket 劫持)

传统的 NAT（网络地址转换）或者 Port Forwarding（端口转发）在修改目的地址和端口的那一瞬间，包就“失真”了。
你的 V2Ray 或 Clash 代理软件无法得知用户原本到底想去哪个真实的远端服务器，除非引入繁重的连接跟踪还原技术（如 REDIRECT + SO_ORIGINAL_DST）。

而 **TPROXY (Transparent Proxy)** 是透明代理的终极手段。这意味着你可以把流量神不知鬼不觉地塞进本机的代理程序（你的 V2ray），**而不需要篡改它的目的 IP 和端口。**

这需要 `nftables` 和 `iproute2` 的顶配联动：

**区别对比：**
- **REDIRECT:** 本质是 DNAT 到 `127.0.0.1` 加上特定端口。原目标 IP 丢失。且仅限 TCP。
- **DNAT:** 跟 REDIRECT 差不多，把信封的目的地址划掉换成本地。
- **TPROXY:** 不修改任何信封内容（不修改 IP 报头），只是通过底层的 Socket 操作，强制当前系统上那个正在监听 1234 端口的代理进程**认领**这个数据包！

---

## 3. 联动实战：基于 Docker 的 TPROXY 透明代理验证

我们来手写一个最简单的透明代理分流，这是所有科学上网插件（如 Clash、V2Ray Tun 模式）底层的核心基石：使用 `fwmark` 结合 TPROXY 搭建旁路网关。

为了直观验证，我们在任意空目录准备两个文件，利用 Docker 复现这一过程。

### 步骤 0：准备测试环境

**第一步：准备 Python 写的假代理服务端 `tproxy_server.py`**
TPROXY 与普通端口转发不同，接收端必须开启特殊的 `IP_TRANSPARENT` Socket 选项，否则内核会因为目标 IP 不是本机而拒收 SYN 握手包。
```python
# 文件：tproxy_server.py
import socket

IP_TRANSPARENT = 19 # Linux 下的 TPROXY 标志位

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.setsockopt(socket.IPPROTO_IP, IP_TRANSPARENT, 1) # 开启透明接收特权

s.bind(('0.0.0.0', 12345))
s.listen(5)
print("TPROXY Server listening on port 12345...", flush=True)

while True:
    conn, addr = s.accept()
    dest_ip, dest_port = conn.getsockname() # TPROXY 的魔法：这里能拿到客户端原本想访问的真实目的IP！
    conn.recv(1024) # 消耗掉 HTTP GET 请求
    
    msg = f"HTTP/1.1 200 OK\r\n\r\nIntercepted connection from {addr[0]}:{addr[1]} destined for {dest_ip}:{dest_port}\n"
    conn.sendall(msg.encode('utf-8'))
    conn.close()
```

**第二步：准备 `docker-compose.yml` 拓扑**
我们设计一个局域网，包含一台网关路由器 (`tproxy_router`) 和一台无辜吃瓜群众 (`tproxy_client`)，吃瓜群众的网关指向这台路由器。
```yaml
services:
  router:
    image: alpine:latest
    container_name: tproxy_router
    cap_add: [NET_ADMIN]
    sysctls: [net.ipv4.ip_forward=1]
    volumes: ["./tproxy_server.py:/tproxy_server.py:ro"]
    command: sh -c "apk add --no-cache iproute2 nftables python3 && python3 /tproxy_server.py & tail -f /dev/null"
    networks:
      lan: { ipv4_address: 10.10.10.254 }

  client:
    image: alpine:latest
    container_name: tproxy_client
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache curl && ip route del default || true && ip route add default via 10.10.10.254 && tail -f /dev/null"
    networks:
      lan: { ipv4_address: 10.10.10.2 }
    depends_on: [router]

networks:
  lan:
    ipam: { config: [{ subnet: 10.10.10.0/24 }] }
```
运行环境：`docker compose up -d`

---

### 步骤 1: 黑洞引流 (100号路由表)
你要让 100 号表的流量，统统引流到了操作系统内核的一个虚拟空洞 `lo` (Local) 路由接口上。
```bash
docker exec tproxy_router ip rule add fwmark 100 lookup 100
# 将带有 100 标记的全部塞回本机的 Local 回环网络
docker exec tproxy_router ip route add local default dev lo table 100
```

### 步骤 2: 配置 nftables TPROXY 劫持
数据包在路由器 `prerouting` 最早的接入口，被 `nftables` 直接判定。如果是去国外的流量（我们模拟访问 `8.8.8.8`）：
1. 立马打上标记 `100`。
2. 下达 `tproxy` 指令，强制把它塞给本机的 `12345` 端口的代理进程。

我们在主机目录下创建 `tproxy.nft`：
```bash
# 文件: tproxy.nft
flush ruleset
table inet mangle {
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;
        
        # 1. 假设对方是国外的 IP，并且是 TCP 协议 (TPROXY 必须指定四层协议)
        # 注意：在 inet 表中，必须显式指定 tproxy ip，否则内核不知道按 IPv4 还是 IPv6 转发
        meta l4proto tcp ip daddr 8.8.8.8 meta mark set 100 tproxy ip to 127.0.0.1:12345 accept
    }
}
```
注入生效：
```bash
docker cp tproxy.nft tproxy_router:/tmp/tproxy.nft
docker exec tproxy_router nft -f /tmp/tproxy.nft
```

### 步骤 3: 见证伟大的终极劫持

打开你的被代理客户端，尝试毫无自觉地访问那台远古服务器（模拟）：
```bash
docker exec tproxy_client curl -s 8.8.8.8
```

不可思议的事情发生了，你的屏幕上赫然出现回显：
```text
Intercepted connection from 10.10.10.2:34316 destined for 8.8.8.8:80
```

**最终执行流全貌：**
数据包（目的地 8.8.8.8）到达路由器网卡 `eth0` → 进入 `nftables prerouting` → 命中 8.8.8.8 规则，打上标志 100，并绑定 tproxy 属主目标 `127.0.0.1:12345` → 包往下走进入 `iproute2` → `ip rule fwmark 100` 命中 → 去查 100 号表 → 100 表将其交给 `lo` 接口送给本地栈 → 内核惊喜地发现这个包有 tproxy 特权章，于是无视了它目的 IP (8.8.8.8) 不在自己身上这个致命事实，乖乖地将连接交给了本地 12345 端口监听的 Python 脚本无损接管！

这就是 Linux 极客们玩弄网络的艺术。有了全局变量的桥接，没有什么是不可拦截的。

下一阶段，我们将目光转向一个特定的硬件系统和 RTOS：OpenWrt。请看：**《扩展阶段三：OpenWrt 环境下的硬核生存指南》**。

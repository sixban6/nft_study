# 期末综合测试卷 (实战演练)

**考试说明：**
你可以查阅任何官方文档或之前的学习资料。但请不要直接复制粘贴答案，必须在脑海中（或草稿纸上）先把逻辑推理出来。这套试卷就是按照真实的工程师面试题来出的。

---

## 第一部分：理论概念题 (每题 10 分)

1. **如果在服务器上同时跑千条以上的规则，为什么说 `nftables` 比 `iptables` 性能好得多？请从底层实现和数据结构两个角度分别回答。**

2. **在 `nftables` 中，`drop` 和 `reject` 的核心区别是什么？在面向公网不可信流量时，通常推荐用哪一个？为什么？**

3. **如果我们要把局域网内的某台 Docker 容器内部端口映射到公网，应该在 Netfilter 的哪一个 Hook 点做工作？为什么？**

4. **在使用 TPROXY 做透明代理拦截外部流量时，为什么说光靠 `nftables` 的 `tproxy` 指令不够，还必须配合 `iproute2` 的 `fwmark` 与策略路由？**

---

## 第二部分：代码查错题 (每题 15 分)

**4. 下面的防火墙脚本导致管理员连不上服务器，请指出包含的安全致命错误，并给出修改方案。**
```nftables
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        iifname "lo" accept
        tcp dport 22 accept
        tcp dport 80 accept
    }
    
    chain output {
        type filter hook output priority 0; policy drop;
    }
}
```

**5. 你的服务器插了两根网线（电信和联通），默认网关是电信。当你从外网 `ping` 你的联通 IP 时，抓包显示包进来了，服务器也产生了回包，但外网就是收不到响应（表现为超时丢包现象）。请解释发生了什么，以及如何使用 `iproute2` 解决这个问题？**

---

## 第三部分：综合实战大作业 (40 分)

**6. 需求文档：编写一份合格的生产环境企业边界防火墙 `boundary_fw.nft`**

你的服务器是一台连接了公网和内网的边界网关，目前运行着 OpenWrt 及其 `fw4` 框架。
- 公网网卡：`eth0`
- 内网网卡：`eth1`，内网包含两个网段：管理网段 `192.168.100.0/24` 和访客网段 `192.168.200.0/24`。

**核心防护要求：**
1. **原子更新**：脚本必须具备全量覆盖而不中断现有安全环境的能力。
2. **白名单防御机制**：INPUT 链默认不放行任何包，状态非法包直接丢弃；接受已存在的连接回包；放行本地回环。
3. **黑名单封禁**：创建一个动态集合（命名集合）叫 `evil_ips`，如果在里面，无论请求什么直接丢弃。默认放入 `1.1.1.1` 测试。
4. **服务开放分流**：使用 `vmap` 实现对公开放端口。22 端口放行，80和443 放行。
5. **NAT 上网功能**：局域网内的机器（来自 `eth1`）想访问互联网，必须通过这台网关做 SNAT（自动伪装）。
6. **[进阶要求] OpenWrt `fw4` 底层注入**：通过手写原生的 `nftables` 链 `guest_isolation`，严禁访客网段 (`192.168.200.0/24`) 访问管理网段的网关 IP (`192.168.100.1`)，但允许访客正常访问外网。并将该链挂载到 `fw4` 的 `forward` 钩子中。

===================== 下方是答案区 =====================



<br><br><br><br><br><br><br><br><br><br>

---

## 测试卷答案解析与得分点

### 第一部分

**1. 性能原因 (10分)**
*   **底层：** `nftables` 支持增量更新。新增或修改一条规则时，不会像 `iptables` 那样将全部规则从内核拖出再塞回，不存在网络瞬断现象。(5分)
*   **数据结构：** `nftables` 原生支持集合 (Sets) 和字典映射 (Vmap)，能将大量 IP 条件或端口分支的 O(N) 线性查找，优化为哈希树的 O(1) 或 O(logN) 查找。(5分)

**2. Drop 与 Reject 的区别 (10分)**
*   `drop`：立刻把包丢弃，不返回任何信息；`reject`：丢弃包的同时，返回一个 ICMP 报错信息给发送方（如连接被拒绝）。(5分)
*   对待公网不可信流量推荐使用 `drop`。因为静默丢弃不仅可以隐蔽服务器的存在（减少被扫描特征），对方干等超时还能消耗攻击者的连接资源。(5分)

**3. 端口映射的 Hook 点 (10分)**
*   必须使用 **Prerouting (路由前)** Hook。(5分)
*   **因为**：如果在路由前不把原本指向宿主机的目标地址改写为内部容器的地址，内核协议栈一经过路由查询，发现就是发给本机的，包就会被送到 INPUT 链，导致映射失败。(5分)

**4. 为什么 TPROXY 必须联动 iproute2 (10分)**
*   `nftables` 的 `tproxy` 指令只能在内核态将该数据包强行与本地某个监听了对应端口的 Socket 绑定。但此时数据包依然在排队等待“路由选择”。(5分)
*   正常情况下，目标 IP 是外网的包，主路由表一定会把它发给外网网关。所以必须给包打上 `fwmark`（比如 100），并借助 `ip rule fwmark 100` 让它去查阅包含 `local` 本地投递机制的私有路由表，才能将包成功交到本机的应用层。(5分)

### 第二部分

**5. 代码致命错误 (15分)**
*   **致命错误**：Output 链的默认策略写成了 `policy drop;`，且没有添加**任何**允许出站的规则！这意味着服务器变成了一个彻头彻尾的黑洞，虽然外面能把请求发进来（比如请求了 22 端口），但是 SSH 服务的响应包在 Output 链被打回了。你永远拿不到回包。(10分)
*   **修改方案**：
    方案A：将 `policy drop;` 改为 `policy accept;`。(最简单省事)
    方案B：由于它没有使用状态机制，最安全的做法是在 Output 明确放行 `ct state established,related accept`。（5分）

**6. 多线路由丢包的原因与解决 (15分)**
*   **原因解释 (Asymmetric Routing)**：包从联通线路（网卡2）进入了内核。服务器回复包时，源 IP 变成了联通的 IP，但是它去翻看主路由表，发现默认网关只有电信。于是包被从电信口发给了电信运营商。电信网关为了防止源地址欺骗（rp_filter），直接将这个自称联通 IP 的脏包丢弃。(8分)
*   **解决方案 (Policy Routing)**：依靠源地址策略路由解决。
    1. 建立一张专属联通的路由表（如 200 号表），里面默认网关统统走联通口。
    2. 利用 `ip rule add from <服务器联通IP> lookup 200`。(7分)

### 第三部分

**7. 综合实战大作业代码参考 (40分)**
*(你的代码逻辑只要相似即可拿满分)*

```nftables
#!/usr/sbin/nft -f

# 1. 确保原子更新 (5分)
flush ruleset

# 6. OpenWrt fw4 隔离要求 (10分)
table inet fw4 {
    chain guest_isolation {
        ip saddr 192.168.200.0/24 ip daddr 192.168.100.1 drop
        accept
    }
}
# 强行将这个链挂载到 fw4 的主 forward 转发逻辑前
nft 'add rule inet fw4 forward jump guest_isolation'

table inet filter {
    # 3. 创建动态命名集合做黑名单 (5分)
    set evil_ips {
        type ipv4_addr
        elements = { 1.1.1.1 }
    }

    chain input {
        # 2. 默认阻断 (5分)
        type filter hook input priority 0; policy drop;

        # 2. 状态机制与基础安全 (3分)
        ct state established,related accept
        ct state invalid drop
        iifname "lo" accept

        # 3. 黑名单最高优先级丢弃 (2分)
        ip saddr @evil_ips drop

        # 4. 服务分流 vmap (5分)
        tcp dport vmap {
            22 : accept,
            80 : accept,
            443: accept
        }
    }

    chain forward {
        type filter hook forward priority 0; policy drop;
        # 必须允许内网转发上网
        iifname "eth1" oifname "eth0" accept
        # 允许转发回包
        ct state established,related accept
    }

    chain output {
        type filter hook output priority 0; policy accept;
    }
}

# 5. 上网 NAT 能力 (5分)
table ip nat {
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        # 内网地址自动伪装成出接口公网 IP
        ip saddr { 192.168.100.0/24, 192.168.200.0/24 } oifname "eth0" masquerade
    }
}
```

> **阅卷寄语：** 如果这套大作业你能够凭借理解默写出绝大部分逻辑，那么这就证明，你不再是对着教程盲目敲打命令的生手，而是一名初步在握、能以编程逻辑驾驭内核底层路由与防火墙框架的高级网络工程师了。祝贺你，终于可以下山了！

# hemabot_ui

Interface web para operar o robô hospitalar **Hemabot** pela rede local, a partir de um
celular ou computador. Nesta primeira versão ela oferece **controle manual**:

- joystick na tela (toque ou mouse) e teclado (`W A S D` / setas, `Espaço` para parar);
- ajuste de velocidade (10–100% dos limites configurados);
- um piloto por vez: os outros usuários acompanham o estado e podem tomar o controle;
- botão **PARAR** disponível para todos os usuários conectados.

O servidor roda no Raspberry Pi do robô, sobe sozinho no boot junto com o ROS 2
(`minihema_launch`) e publica os comandos em `/cmd_vel_joy`, uma das entradas do
`twist_mux` do [hemabot_ros2](https://github.com/ZimaUSP/hemabot_ros2).

## Instalação no robô

Pré-requisitos: Ubuntu Server 22.04, ROS 2 Humble instalado e o workspace `hemabot_ros2`
compilado (`colcon build`), como descrito em `hemabot_ros2/docs/os_installation_raspberry.md`.

```bash
cd ~
git clone https://github.com/ZimaUSP/hemabot_ui.git
cd hemabot_ui
sudo ./scripts/setup.sh
```

O `setup.sh`:

1. instala `python3-venv`, `python3-pip` e `avahi-daemon` (para o endereço `hemabot.local`);
2. adiciona o usuário aos grupos de hardware existentes (`dialout`, `i2c`, `gpio`, `input`, `video`);
3. cria o virtualenv `.venv` (com acesso ao `rclpy` do sistema) e instala a aplicação;
4. cria a configuração `/etc/hemabot/hemabot.env` (mantida se já existir);
5. instala, habilita e inicia os serviços `hemabot-ros` e `hemabot-ui`;
6. libera a porta no `ufw`, se ele estiver ativo.

Opções úteis: `--user NOME`, `--ros-ws CAMINHO` (padrão `~/hemabot_ros2`), `--port N`
(padrão 80), `--skip-apt`, `--no-start`. Veja `sudo ./scripts/setup.sh --help`.

Ao final ele mostra os endereços de acesso, por exemplo `http://hemabot.local` ou
`http://192.168.1.155`. O celular precisa estar na mesma rede Wi-Fi do robô.

Para atualizar: `git pull && sudo ./scripts/setup.sh`. Para remover os serviços:
`sudo ./scripts/uninstall.sh` (`--purge` também apaga `/etc/hemabot`).

### Serviços

| Serviço         | O que faz                                                        |
|-----------------|------------------------------------------------------------------|
| `hemabot-ros`   | `ros2 launch minihema_launch minihema_launch.py` no workspace     |
| `hemabot-ui`    | servidor web (depende de `hemabot-ros` e o inicia junto)          |

```bash
systemctl status hemabot-ros hemabot-ui
journalctl -u hemabot-ros -u hemabot-ui -f      # logs ao vivo
sudo systemctl restart hemabot-ros              # reiniciar a pilha ROS
```

> **Importante:** com o `hemabot-ros` ativo, não rode o `minihema_launch` (ou o
> `start_hema.sh`) manualmente — os dois disputariam motores, IMU e LiDAR. Para rodar à mão,
> pare antes o serviço: `sudo systemctl stop hemabot-ros`.
>
> A calibração da IMU (`calibrar_offsets`, `calibrar_covariancias.sh`) **não** roda no boot:
> ela exige o robô parado e recompila o workspace. Rode-a manualmente quando necessário e
> depois `sudo systemctl restart hemabot-ros`.

### Configuração

Edite `/etc/hemabot/hemabot.env` e reinicie os serviços. Principais variáveis:

| Variável                        | Padrão           | Descrição                                     |
|---------------------------------|------------------|-----------------------------------------------|
| `HEMABOT_ROS_WS`                | `~/hemabot_ros2` | workspace colcon do robô                       |
| `HEMABOT_ROS_LAUNCH_ARGS`       | vazio            | argumentos extras para o `ros2 launch`         |
| `HEMABOT_UI_PORT`               | `80`             | porta HTTP                                    |
| `HEMABOT_UI_CMD_VEL_TOPIC`      | `/cmd_vel_joy`   | tópico `geometry_msgs/Twist` de saída         |
| `HEMABOT_UI_MAX_LINEAR_SPEED`   | `0.4`            | velocidade linear máxima (m/s)                |
| `HEMABOT_UI_MAX_ANGULAR_SPEED`  | `1.0`            | velocidade angular máxima (rad/s)             |
| `HEMABOT_UI_COMMAND_TIMEOUT_S`  | `0.4`            | sem comandos do piloto por esse tempo → para  |
| `ROS_DOMAIN_ID`                 | (comentado)      | isola o robô de outras máquinas ROS na rede   |

Todas as opções estão em [`src/hemabot_ui/config.py`](src/hemabot_ui/config.py).

### Diagnóstico

```bash
source /opt/ros/humble/setup.bash
~/hemabot_ui/.venv/bin/hemabot-ui doctor
```

O `doctor` verifica o ambiente ROS, se o `rclpy` importa, se há alguém (o `twist_mux`)
inscrito em `/cmd_vel_joy`, se `twist_mux` e `controller_manager` estão rodando e se o
servidor web responde. Na interface, o indicador **"Aguardando ROS"** significa que o
servidor está no ar mas a pilha ROS ainda não está consumindo os comandos.

Testes de integração com o ROS real (usam um tópico próprio, não movem o robô):

```bash
source /opt/ros/humble/setup.bash
cd ~/hemabot_ui && .venv/bin/pip install pytest pytest-asyncio pytest-timeout httpx
.venv/bin/python -m pytest -m ros
```

## Segurança do controle

- Só o piloto move o robô; tomar o controle de outro usuário exige confirmação e para o robô.
- O navegador reenvia o comando a 10 Hz enquanto há movimento. Se nada chegar por
  `command_timeout_s` (queda de Wi-Fi, aba em segundo plano, celular bloqueado), o servidor
  para o robô sozinho.
- Ao parar, são publicadas algumas mensagens de velocidade zero e o tópico fica em silêncio,
  para não atrapalhar o joystick físico, que usa o mesmo tópico.
- **PARAR** (ou `Espaço`) funciona para qualquer usuário e também retira o controle do piloto,
  para que um joystick ainda pressionado não volte a mover o robô.
- Desconectar o piloto, encerrar o servidor ou `systemctl stop` também param o robô.

## Arquitetura

```
src/hemabot_ui/
├── motion/            domínio de movimento + backends
│   ├── velocity.py    DriveIntent (normalizado) → VelocityCommand (m/s, rad/s)
│   ├── backend.py     interface MotionBackend
│   ├── ros2.py        publica geometry_msgs/Twist via rclpy
│   └── simulated.py   backend em memória (desenvolvimento e testes)
├── teleop/            regras de teleoperação, independentes de web e de ROS
│   ├── pilot.py       arbitragem de piloto único
│   └── service.py     watchdog, taxa de publicação, parada de emergência
├── web/
│   ├── protocol.py    mensagens JSON do WebSocket (validadas com pydantic)
│   ├── gateway.py     liga clientes WebSocket ao TeleopService
│   ├── hub.py         conexões e broadcast
│   ├── app.py         FastAPI: /api/health, /ws/teleop e arquivos estáticos
│   └── static/        cliente web (HTML/CSS/ES modules, sem etapa de build)
├── bootstrap.py       composição: Settings → objetos conectados
├── config.py          configuração por variáveis HEMABOT_UI_*
├── doctor.py          diagnóstico da instalação
└── cli.py             `hemabot-ui serve | doctor`
deploy/                units systemd, scripts de start e modelo de configuração
scripts/               setup.sh e uninstall.sh
tests/                 pytest (unit, web, deploy, system, ros) e tests/js (node:test)
```

A lógica de teleoperação só conhece a interface `MotionBackend`; o ROS fica isolado em
`motion/ros2.py`. Novas funcionalidades (navegação até destinos, mapa, câmera, bateria...)
entram como novos módulos ao lado de `teleop/`, com suas rotas em `web/`.

### Protocolo do WebSocket (`/ws/teleop`)

| Direção          | Mensagem                                              |
|------------------|-------------------------------------------------------|
| cliente → server | `{"type": "acquire", "force": false}`                 |
| cliente → server | `{"type": "drive", "linear": 0.5, "angular": -0.2}` (normalizado em [-1, 1]; angular positivo = esquerda) |
| cliente → server | `{"type": "release"}` / `{"type": "stop"}`            |
| server → cliente | `welcome` (id e limites), `state` (piloto, clientes, estado do robô), `error` (código) |

## Desenvolvimento

Sem robô e sem ROS, usando o backend simulado:

```bash
uv sync
uv run hemabot-ui serve --backend simulated      # http://localhost:8080
```

Testes e qualidade:

```bash
uv run pytest              # Python + testes JS (precisa de node ≥ 18)
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

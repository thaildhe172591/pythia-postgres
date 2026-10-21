# pythia-postgres

[English](README.md) · **Tiếng Việt**

pythia cho PostgreSQL: phát triển PL/pgSQL cho AI agent, xây trên
[pythia-core](https://github.com/thaildhe172591/pythia-core). Nó nhắm làm
được điều mà [pythia](https://github.com/thaildhe172591/pythia) làm trên
Oracle: agent học từ catalog đang chạy, hỏi một người trước mọi lần ghi, và
chỉ ghi qua một cổng có snapshot, có kiểm chứng và báo cáo trung thực.

**Alpha (0.1.1).** Nó đọc được mọi thứ mà nhịp Học của pythia cần, và ghi
qua một cổng duy nhất. Mọi lần ghi đều được rehearse trong một transaction,
đưa ra cho xem, được dev duyệt — trong chat của agent hoặc ở console của họ
— và chỉ commit đúng như đã duyệt. `pythia-pg install` chuẩn bị một project
cho agent: một guard chặn `psql` ghi vòng qua cổng, luật trong mọi phiên,
và các skill `pythia-pg-*`. Lộ trình, và cách mỗi ý tưởng của pythia ánh xạ
sang PostgreSQL, nằm trong
[DESIGN.md](https://github.com/thaildhe172591/pythia-core/blob/main/DESIGN.md)
của pythia-core. Mỗi cổng chặn được gì, và không chặn được gì, nằm trong
[SECURITY.md](https://github.com/thaildhe172591/pythia-core/blob/main/SECURITY.md)
của nó.

| Đã dùng được |
|---|
| đọc: `check`, `ls`, `src`, `cols`, `ddl`, `grep`, `deps`, `impact`, `errors`, `connections` |
| ghi: `apply`, `deploy`, `approve` (console, chat, MCP), `journal`, `history`, `policy`, `autopilot`, `lint` |
| harness: `install`, `doctor`, `hook`, `mcp`, `skill lint` |

Đã test trên PostgreSQL 14 đến 18, mỗi bản qua toàn bộ live check; 14 là
phiên bản tối thiểu, và thấp hơn thì `check` nói rõ (không gì bị từ chối).
`plpgsql_check` là tuỳ chọn: có nó, `errors` và mọi preview kiểm
PL/pgSQL; không có, chúng ghi `NOT VERIFIED`.

## Cài đặt

```bash
pip install pythia-postgres
```

Lệnh này kéo theo pythia-core, và psycopg 3 kèm libpq riêng của nó
(`psycopg[binary]`), nên không cần cài PostgreSQL client nào. Bản đang phát
triển là nhánh main của cả hai:

```bash
pip install "git+https://github.com/thaildhe172591/pythia-core" \
            "git+https://github.com/thaildhe172591/pythia-postgres"
```

## Chuẩn bị một project cho agent

```bash
cd your-project
pythia-pg install     # once; a second run changes nothing
pythia-pg doctor      # is everything wired? exit 1 names what is not
```

`install` ghi những thứ sau, và giữ nguyên mọi thứ khác:

- `.pythia/postgres/connections.json`, mode 600, tạo một lần từ template —
  dev tự điền mật khẩu; agent không bao giờ mở file này;
- các dòng `.gitignore` cho file đó, cho các lần duyệt của máy này
  (`.pythia/postgres/grants/`) và cho `.claude/settings.local.json`;
- `.claude/settings.local.json`: các hook (guard, bản tóm tắt đầu phiên,
  câu trả lời AskUserQuestion), ghi bằng đường dẫn tuyệt đối của interpreter
  này để chúng chạy được dù virtual environment có được kích hoạt hay không,
  và các deny rule cho file của engine;
- MCP approver `pythia_pg` (tool `pythia_pg_approve`), chỉ trong file riêng
  của máy này: local scope của Claude Code cho project (`~/.claude.json`) và
  `~/.codex/config.toml` của Codex, mỗi cái khi client đó đã từng chạy ở đây;
- một khối `pythia-pg` trong CLAUDE.md và AGENTS.md (khối của pythia cho
  Oracle, và chữ của chính dev, được giữ nguyên);
- các skill, trong `.claude/skills` và `.agents/skills`: `using-pythia-pg`
  (bộ định tuyến), `pythia-pg-explore`, `pythia-pg-impact`,
  `pythia-pg-apply`, `pythia-pg-deploy`, `pythia-pg-autopilot`,
  `pythia-pg-verify`.

Sau khi cài, khởi động lại phiên của agent để hook được nạp. Từ đó mỗi phiên
bắt đầu bằng các luật và một dòng `STATE` (connection, write policy). Trước
mỗi lần gọi tool, guard quyết định:

| Agent chạy | Guard |
|---|---|
| `psql` được đưa SQL ghi, `-f`, `< file`, một pipe, `\i`; `pg_restore` — kể cả sau `docker exec`, `ssh`, `sudo` hay `bash -c` | chặn: mọi lần ghi đi qua `pythia-pg apply` |
| một MCP SQL tool được đưa SQL ghi | chặn |
| đọc `connections.json`; sửa `policy.json`, journal hay một grant; đặt `PYTHIA_PG_CI`; gọi `grants.mint` từ một one-liner | chặn |
| một lệnh đọc của `pythia-pg`, một preview, `approve --card` | cho qua, không hỏi |
| `apply --confirm <token>` mà dev đã duyệt trên connection này | cho qua; apply kiểm lại |
| `psql` chỉ đọc, `approve`, `--yes`, `policy set`, mọi lệnh ghép | đứng ngoài: client tự hỏi |

Guard đọc một lệnh theo những gì nó gọi tên, không theo ý nghĩa của nó: nó
có thể chặn một lệnh vô hại, và bỏ lọt một lần ghi được viết theo cách nó
không liệt kê. Cổng phía sau vẫn giữ được trong cả hai trường hợp
(SECURITY.md của pythia-core).

pythia-mssql và pythia-mongo cài cạnh nó trong cùng một project, và pythia
cho Oracle cũng vậy: mỗi bên giữ nguyên hook và khối hướng dẫn của các bên
khác, và guard cùng hook duyệt của mỗi bên chỉ hành động cho chính công cụ
của nó (CI của pythia-core kiểm tra điều này khi cả bốn cùng được cài).

## Connection

`.pythia/postgres/connections.json` ở gốc project, chỉ chủ sở hữu được đọc
(`chmod 600`), và nằm ngoài git — `pythia-pg install` làm cả ba việc đó.
Template:
[examples/connections.example.json](https://github.com/thaildhe172591/pythia-postgres/blob/main/examples/connections.example.json).

```json
{
  "default": "dev",
  "dev": { "host": "db-dev", "port": 5432, "dbname": "app",
           "user": "app_agent", "password": "...", "schema": "APP_OWNER" }
}
```

- `host`, `dbname`, `user` là bắt buộc. Không có `password` thì libpq dùng
  các nguồn riêng của nó (`PGPASSWORD`, `~/.pgpass`). `sslmode` và
  `connect_timeout` (giây, mặc định 10) là tùy chọn.
- `schema` được chuyển về chữ thường, như PostgreSQL làm với một tên không
  đặt trong ngoặc kép; mặc định là `public`. `check` cảnh báo khi
  `search_path` của phiên đưa tên không đủ định danh sang nơi khác.
- Entry được chọn theo `--conn NAME`, rồi `PYTHIA_PG_CONNECTION`, rồi entry
  duy nhất, rồi thư mục nằm ngay dưới gốc project, rồi `"default"`. Mọi chỗ
  mơ hồ đều là lỗi. `PYTHIA_PG_CONFIG` trỏ tới một file khác.

**Cạnh pythia cho Oracle:** pythia giữ connection của nó trong
`.pythia/connections.json`, và pythia-pg không bao giờ đọc file đó. Lệnh
(`pythia-pg`) và các biến (`PYTHIA_PG_*`) của nó cũng không bao giờ đụng với
của pythia.

## Các lệnh

Mọi lệnh đều mở một phiên chỉ đọc: chính PostgreSQL từ chối một lần ghi
trong phiên đó.

```bash
pythia-pg check                  # server, database, schema, search_path drift
pythia-pg ls "t_order%"          # objects by LIKE pattern, any case
pythia-pg src f_order_total      # source as PostgreSQL prints it, one unit per overload
pythia-pg cols t_order           # columns, defaults, comments
pythia-pg ddl t_order            # CREATE statement: tables rebuilt from the catalog
pythia-pg grep "t_order where"   # every source line holding a text
pythia-pg deps f_order_paid      # what it depends on
pythia-pg impact t_order         # what depends on it: run before changing it
pythia-pg errors [NAME]          # plpgsql_check's findings, or why there are none
pythia-pg connections            # entries without their secrets
```

Tên được chuẩn hóa như PostgreSQL: `T_ORDER` là `t_order`, còn
`'"MixedCase"'` được giữ đúng nguyên văn. `--json` cho một envelope mỗi
lệnh. `--limit`, `--max-lines` và `--offset` phân trang output dài, và mọi
chỗ bị cắt đều nói cách lấy phần còn lại.

### Những gì catalog không thấy, và pythia-pg nói ra thế nào

- **`deps` và `impact` hỏi hai lần.** `pg_depend` ghi lại view, materialized
  view, thân function theo chuẩn SQL (`BEGIN ATOMIC`), trigger, constraint,
  default của cột và policy. Nó không nhìn vào thân PL/pgSQL, hay một SQL
  function có thân là một chuỗi. Những thứ đó được tìm bằng cách tìm nguyên
  từ trong source của function và đánh dấu `[text]`: một manh mối, không
  phải bằng chứng. Mỗi lần chạy đều in ra các điểm mù này: tên được ghép lúc
  chạy (`EXECUTE format(...)`), và các database, server khác.
- **`impact` nói khi nào phải dừng.** Từ 10 dependent trở lên, hoặc có
  dependent ở schema khác, nó bảo hãy trình danh sách cho dev trước khi viết
  code.
- **`errors` không bao giờ trông như sạch khi thật ra không sạch.**
  PostgreSQL chỉ kiểm cú pháp khi tạo một PL/pgSQL function. Không có
  extension `plpgsql_check`, `errors` in `NOT VERIFIED` và nói cách thêm nó.
  Có extension, tên không đủ định danh được phân giải với schema đã cấu hình
  đứng đầu `search_path`, như ứng dụng của schema đó vẫn làm. Nếu tài khoản
  không có `USAGE` trên schema, `errors` không báo gì và nêu đúng lệnh
  `GRANT` cần có. Không có `USAGE`, mọi tên sẽ trông như bị thiếu.
- **`ddl` của một table được dựng lại, không phải dump.** Nó được dựng lại
  từ catalog: cột, identity, cột generated, constraint, index, trigger và
  comment. Bộ test chứng minh vòng khứ hồi: drop table, chạy DDL, dựng lại,
  so sánh. `pg_dump --schema-only` vẫn là chuẩn tham chiếu cho những gì nó
  chưa bao phủ, và output nói rõ là những gì.

### Ghi: cổng

```bash
pythia-pg apply change.sql                   # preview: rehearsed, rolled back, nothing written
pythia-pg approve 3fa9c1                     # the developer approves (or from chat, below)
pythia-pg apply change.sql --confirm 3fa9c1  # writes it — only as approved
pythia-pg journal restore <entry>            # undo is a write too: preview, approve, confirm
pythia-pg policy                             # which groups may be written, and is rollback real?
```

Dev duyệt qua cánh cửa đầu tiên dùng được:

1. **Trong chat của Claude Code.** Agent hỏi bằng AskUserQuestion, nội dung
   đúng nguyên văn output của `pythia-pg approve --card <token>`, hai lựa
   chọn Approve / Reject. Hook nhận câu trả lời chỉ ghi nhận lần duyệt khi
   câu hỏi mang đúng thẻ đó và chính dev chọn Approve — không phải câu trả
   lời do agent viết, không phải một hộp thoại tự đóng khi không có ai.
2. **Qua MCP approver** (`pythia_pg_approve`; Codex bắt đầu từ đây): client
   hiện thẻ, và chỉ một lần Approve rõ ràng mới được tính.
3. **Ở console của dev:** `pythia-pg approve <token>`.

`pythia-pg doctor` cảnh báo những thiết lập có thể tự trả lời cánh cửa chat
thay cho dev (chế độ `dontAsk`, một allow rule cho AskUserQuestion, một hook
khớp mọi tool).

### Một release: `deploy`, một transaction

```bash
pythia-pg deploy 01_schema.sql 02_data.sql                    # preview the release as one transaction
pythia-pg deploy 01_schema.sql 02_data.sql --confirm 9c41e0b2aa  # all of it, as approved, or none
```

Một release — một hay nhiều script, các câu lệnh kết thúc bằng `;` — được
rehearse trong một transaction: từng câu lệnh theo thứ tự, snapshot trước
khi chạy, số dòng và kết quả kiểm chứng lấy tại đúng thời điểm của nó (một
UPDATE trên cột mà chính release thêm vào được rehearse với cột đó), rồi tất
cả được rollback. Một thẻ hiện mọi câu lệnh, và một lần duyệt (token 10 chữ
số, qua cùng các cánh cửa) phủ cả release; token của một câu lệnh lẻ không
được duyệt riêng. Lúc confirm, nó kiểm từng câu lệnh giống hệt từng byte với
bản đã duyệt trước khi chạy gì, chạy lại release trong một transaction, và
chỉ commit nếu mọi câu lệnh vẫn khớp. Một câu lệnh lỗi, hoặc dòng, object
hay kết quả kiểm chứng đã thay đổi, sẽ rollback cả release: không phần nào
nằm lại dở dang. Bị từ chối trước khi chạy gì: `SET` trong một release, và
mọi thứ `apply` từ chối.

### Lint: trước mọi lần apply

```bash
pythia-pg lint 01_schema.sql 02_code.sql   # a change's files in one run
pythia-pg lint --rules                     # every rule and its effective severity
```

Các rule đọc những gì PostgreSQL chấp nhận mà một người review thì không:

| Rule | Mặc định | Vì sao |
|---|---|---|
| `pg-definer-search-path` | error | một function `SECURITY DEFINER` (tạo mới hay sửa) không có `SET search_path` có thể bị chiếm quyền bởi bất kỳ ai tạo được object trên path của người gọi |
| `pg-timestamp-without-tz` | warn | `timestamp` lưu giờ đồng hồ treo tường, không phải một thời điểm — dùng `timestamptz` |
| `pg-char-n` | warn | `char(n)` đệm thêm khoảng trắng |
| `pg-money` | warn | `money` phụ thuộc `lc_monetary` — dùng `numeric` |
| `pg-serial` | info | nên dùng `GENERATED ALWAYS AS IDENTITY` |
| `pg-select-star` | warn | `SELECT *` trong view hay function bị đóng băng hoặc gãy khi có cột mới |
| `pg-not-in-subquery` | warn | `NOT IN (SELECT ...)` không bao giờ đúng khi subquery trả về một NULL |
| `pg-table-comment` | warn | một table mới có `COMMENT ON TABLE` của nó trong cùng thay đổi |

Những gì PostgreSQL tự từ chối (một RAISE sai số tham số) được để cho
rehearsal. Team đặt severity và quy ước đặt tên trong
`.pythia/postgres/lint.json`:

```json
{"severity": {"pg-select-star": "error", "naming": "error"},
 "naming": {"FUNCTION": "^f_[a-z0-9_]+$", "VIEW": "^v_[a-z0-9_]+$"}}
```

Mọi preview đều hiện các phát hiện, lỗi của một câu lệnh nằm trên thẻ của
nó, và autopilot không bao giờ ghi một thay đổi còn lỗi lint.

### Autopilot: một lease thay cho từng lần duyệt

```bash
pythia-pg autopilot request --groups source,comments --hours 2 --max-writes 30
pythia-pg autopilot report      # every write under the lease, with its restore
pythia-pg autopilot off         # anyone may revoke
```

Khi dev muốn agent làm việc mà không phải duyệt từng lần ghi, agent xin một
lease. Thẻ của nó nêu connection, các group, thời gian, số lần ghi và có gồm
câu lệnh phá hủy hay không, và chưa có gì được ủy quyền cho tới khi dev duyệt
nó qua một cánh cửa (hoặc tự chạy `pythia-pg autopilot on` ở console). Trong
thời gian lease còn hiệu lực, `apply` và `deploy` ghi những gì nó phủ mà
không cần `--confirm` — vẫn có snapshot, rehearse, kiểm chứng và ghi
journal. Lease không bao giờ phủ một connection khác, một connection đánh
dấu `"protected": true` (hoặc có `"env"` là prod / production / prd /
live), một group hay câu lệnh phá hủy mà thẻ không nêu, hoặc quá 1000 dòng;
một lần ghi làm gãy thứ gì đó, hoặc năm lần thất bại liên tiếp, sẽ tạm dừng
nó.

### Một câu lệnh: `apply`

Mỗi file một câu lệnh. `apply` xếp nó vào một group, và policy quyết định:
`source` (function, procedure, view) và `comments` cần dev duyệt;
`data_dml`, `structural` và `grants` bị từ chối cho tới khi dev chạy
`pythia-pg policy set <group> confirm` ở console. `session` (`SET`) được
phép.

Preview hiện gì, và vì sao có thể tin nó:

- **Một rehearsal, không phải một dự đoán.** Câu lệnh đã chạy trong một
  transaction rồi được rollback. Diff so sánh định nghĩa trước và sau, cả
  hai theo cách PostgreSQL in ra, nên định dạng không gây nhiễu. Khi đã cài
  `plpgsql_check`, nó nói thay đổi đã làm gãy gì so với ngay trước đó; một
  `ALTER TABLE ... DROP COLUMN` nêu tên function mà nó sẽ làm gãy. Không có
  extension đó, preview ghi `NOT VERIFIED`.
- **Overload được gọi tên.** `CREATE OR REPLACE FUNCTION f(int)` bên cạnh
  một `f(text)` đã có sẽ tạo function thứ hai; preview nói rõ điều đó.
- **Dòng được hiện ra và kiểm lại.** Một UPDATE hay DELETE được duyệt trên
  chính các dòng của nó: số lượng, một mẫu, và một dấu vân tay của các ctid.
  Nếu có dòng nào thêm vào, rời đi hay thay đổi trước lúc confirm, lần
  confirm bị từ chối.
- **Confirm là cùng một rehearsal, chỉ commit nếu vẫn khớp.** Cùng token
  (file, object như lúc đó, các dòng), cùng số dòng, và không có gì gãy mà
  preview đã duyệt chưa hiện. Nếu không, nó rollback và nói cái gì đã thay
  đổi.
- **Bị từ chối, kèm lý do:** DO, CALL, SELECT, WITH, lệnh điều khiển
  transaction, SET ROLE, object tạm, meta-command của psql, nhiều câu lệnh
  trong một file, câu lệnh không chạy được trong transaction (`CREATE INDEX
  CONCURRENTLY`, `VACUUM`, ...), và một tên không đủ định danh mà
  `search_path` sẽ đưa sang schema khác với schema đã cấu hình.

Một rehearsal có giới hạn (`statement_timeout` 30 s, `lock_timeout` 5 s). Nó
vẫn chạy trigger và đẩy sequence lên, và preview của một câu lệnh DML nói rõ
điều đó. Exit code theo pythia: `0` sạch, `1` bị từ chối, `3` đã ghi nhưng
gãy (kèm lệnh restore).

### Quyền tối thiểu

Các lệnh đọc chỉ cần `LOGIN`: catalog của PostgreSQL đọc được với mọi role.
`errors` cần thêm `USAGE` trên schema. Ghi cần đúng những gì câu lệnh cần
(để thay một function thì phải sở hữu nó), và preview cảnh báo khi tài khoản
là superuser, tạo được role, hoặc sở hữu schema. Đặt search path cho role
của agent về schema mà nó làm việc:
`ALTER ROLE app_agent IN DATABASE app SET search_path = app_owner, public`.

## Test

```bash
python tests/test_postgres.py   # no database, no psycopg: a stand-in catalog answers by query file; the statement reader; the guard's patterns; the skills
python tests/live_check.py      # a disposable server only (see its docstring)
```

`test_postgres.py` tìm pythia-core đã cài, trong một checkout nằm cạnh
checkout này (`../pythia-core`), hoặc ở `PYTHIA_CORE_SRC`. CI chạy nó trên
Ubuntu, Windows và macOS, Python 3.9 và 3.13. CI cũng chạy live check với
một service container `postgres:16`. Live check nạp
[tests/fixtures/app_owner.sql](https://github.com/thaildhe172591/pythia-postgres/blob/main/tests/fixtures/app_owner.sql)
và kiểm mọi lệnh trên đó: các lệnh đọc, rồi cổng ghi từ đầu đến cuối
(preview, duyệt, confirm, restore, dòng và kết quả kiểm chứng đã thay đổi).
Tất cả chạy cả khi có lẫn khi không có `plpgsql_check`. CI test với nhánh
pythia-core cùng tên khi có, nên một thay đổi trải trên cả hai repository
được test trọn vẹn.

## Giấy phép

MIT

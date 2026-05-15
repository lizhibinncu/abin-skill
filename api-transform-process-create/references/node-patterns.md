# API Transformer Node Patterns

Use this reference when creating or developing non-trivial BYAI API Transformer workflows: data dispatch, HTTP sender, Dubbo sender, database lookup/write, data mapping, or custom result handling.

## Runtime Script Model

- Scripts receive the previous node output as `args`.
- Built-in variables commonly available in scripts:
  - `companyId`, `workflowId`
  - `request` (`HttpServletRequest`)
  - `applicationContext`
  - `args.httpParam` for original HTTP request params
  - `args.apiRawData` when an HTTP sender returns non-JSON data
- `接收数据` credential/check scripts should return `true`/`false`; failed checks throw validation/signature errors.
- `接收数据` decrypt scripts return `Map<String, Object>` and replace runtime variables.
- `数据转换` scripts return `Map<String, Object>` and replace runtime variables.
- `数据映射` script/manual mapping returns or builds `Map<String, Object>` and replaces runtime variables.
- `发送数据` credential scripts return `Map<String, Object>` and append values to runtime variables.
- `发送数据` encryption scripts return `Map<String, Object>` and replace outgoing variables.
- Retry scripts return `boolean`.
- `结束` scripts return the final HTTP response body. Use `return args` for pass-through.
- HTTP sender responses are wrapped as `{ "code": <http status>, "data": <response body> }`.
- Dubbo sender responses are not wrapped; `args` is exactly the Dubbo return value.

## Script Utilities

Common imports used in examples:

```groovy
import org.slf4j.LoggerFactory
import groovy.transform.Field
import cn.hutool.json.JSONUtil
import cn.hutool.json.JSONObject
import cn.hutool.json.JSONArray
import com.byai.apitransformers.domain.common.db.DBUtil
import com.byai.apitransformers.domain.common.http.HttpUtil
import com.byai.apitransformers.domain.common.redis.RedisUtil
```

Logging pattern:

```groovy
@Field
def logger = LoggerFactory.getLogger("workflow-name")
logger.info("args:{}", args)
```

Global variables:

```groovy
$global.put("customerPhone", args.phone)
def customerPhone = $global.customerPhone
```

URI variable substitution for HTTP sender paths:

```groovy
def uriParam = [:]
uriParam.timestamp = timestamp
uriParam.signature = signature
args.uriParam = uriParam
// sender path may contain: https://example.com/callback?timestamp={timestamp}&signature={signature}
```

Database examples:

```groovy
String sql = "SELECT score FROM score_table WHERE company_id = {0} AND phone = {1} LIMIT 1"
def score = DBUtil.selectObj(sql, args.company_id, args.phone) ?: ""
return ["score": score]
```

```groovy
String insertSql = "insert ignore into clue_table(phone, outer_id, status) values ({0}, {1}, {2})"
DBUtil.insert(insertSql, args.phone, args.outerId, args.status)
return ["code": 200, "status": args.status]
```

## Graph Basics

Every workflow draft payload sends:

```json
{
  "workflowName": "...",
  "companyId": 123,
  "companyName": "...",
  "workflowId": 456,
  "graph": { "nodes": [], "edges": [] }
}
```

Edges are simple source-target links:

```json
{ "id": "edge-id", "index": 0, "source": "source-node-id", "target": "target-node-id" }
```

Node `frontParams.position` controls the canvas. Keep `branches: ["默认"]` unless a copied example requires otherwise.

## Node Schemas

### 接收数据 (`API_RECEIVER`)

```json
{
  "id": "00000000",
  "label": "接收数据",
  "nodeType": "API_RECEIVER",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 19600 } },
  "extra": {
    "name": "接收数据-默认",
    "urlPrefix": "https://open-tcs.byai.com/api/transformers/",
    "uri": "callback/suffix",
    "method": "POST",
    "mediaType": "application/json",
    "paramType": 1,
    "paramCheckList": [],
    "paramTree": []
  }
}
```

`mediaType` may be `application/json`, `application/x-www-form-urlencoded`, or `text/plain`. `paramCheckList` entries can include `apiFieldName`, `apiFieldType`, `notNull`, `apiFieldValue`, and optional `checkScript`; mirror the same data into `paramTree` when building a typed receiver.

### 数据转换 (`DATA_CONVERT`)

```json
{
  "id": "convert01",
  "label": "数据转换",
  "nodeType": "DATA_CONVERT",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 19840 } },
  "extra": {
    "name": "数据转换-默认",
    "convertScript": "return args"
  }
}
```

Use this node for request normalization, signature generation, DB lookup/write, Redis reads/writes, and response reshaping before an end node.

### 数据映射 (`DATA_MAPPING`)

```json
{
  "id": "mapping01",
  "label": "数据映射",
  "nodeType": "DATA_MAPPING",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 19830 } },
  "extra": {
    "name": "数据映射-默认",
    "mappingType": "MANUAL",
    "systemType": "CUSTOM",
    "fieldMappingList": [
      {
        "sourcePath": "param.call_instance_id",
        "sourcePathType": "input",
        "targetPath": "req.taskId",
        "targetPathType": "input"
      }
    ]
  }
}
```

Use mapping before Dubbo when the sender parameter must be a named object like `req`.

### 发送数据 HTTP (`API_SENDER`)

```json
{
  "id": "senderHttp01",
  "label": "发送数据",
  "nodeType": "API_SENDER",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 20020 } },
  "extra": {
    "name": "发送数据-HTTP",
    "rpcProtocol": "http",
    "method": "POST",
    "path": "https://example.com/api",
    "mediaType": "application/json",
    "paramType": 1,
    "timeoutSecond": 5,
    "httpHeaderList": [],
    "httpHeaderTree": []
  }
}
```

Optional retry fields seen in examples:

```json
{ "autoRetry": true, "retryNum": 2 }
```

### 发送数据 Dubbo (`API_SENDER`)

```json
{
  "id": "senderDubbo01",
  "label": "发送数据",
  "nodeType": "API_SENDER",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 20020 } },
  "extra": {
    "name": "发送数据-Dubbo",
    "rpcProtocol": "dubbo",
    "dubboRegistry": "host1:2181,host2:2181,host3:2181",
    "serviceName": "service-name",
    "serviceInterface": "com.example.RemoteService",
    "serviceMethod": "methodName",
    "serviceParameterTypes": [
      { "name": "req", "order": 1, "type": "com.example.Request" }
    ],
    "paramType": 1,
    "timeoutSecond": 5,
    "httpHeaderList": [],
    "httpHeaderTree": []
  }
}
```

For multi-argument Dubbo methods, add one `serviceParameterTypes` item per argument with increasing `order`. Upstream data must contain matching keys by parameter name.

### 数据分流 (`DATA_DISPATCH`) And 分支 (`DISPATCH_BRANCH`)

`DATA_DISPATCH` routes by values returned from `dispatchParamScript`. The return values used by branch rules must be strings.

```json
{
  "id": "dispatch01",
  "label": "数据分流",
  "nodeType": "DATA_DISPATCH",
  "frontParams": { "branches": ["默认"], "position": { "x": 19868, "y": 20280 } },
  "extra": {
    "name": "数据分流-默认",
    "dispatchParamScript": "return [\"send\": args.send + \"\"]",
    "switchDefault": false,
    "dispatchJudgeList": [
      {
        "name": "分支1",
        "nextId": "branch01",
        "isDefault": 0,
        "conditions": {
          "relation": "AND",
          "rules": [
            { "field": "send", "operator": "EQUAL", "param": ["0"], "valueType": "STRING", "hasEmpty": false }
          ]
        }
      }
    ]
  }
}
```

Matching branch node:

```json
{
  "id": "branch01",
  "label": "数据分流分支",
  "nodeType": "DISPATCH_BRANCH",
  "frontParams": { "branches": ["默认"], "position": { "x": 19580, "y": 20430 } },
  "extra": {
    "name": "分支1",
    "canDrag": false,
    "conditions": {
      "relation": "AND",
      "rules": [
        { "field": "send", "operator": "EQUAL", "param": ["0"], "valueType": "STRING", "hasEmpty": false }
      ]
    },
    "conditionsZH": {
      "eventLabels": [],
      "userLabels": [[["send", "等于", "0"]]]
    }
  }
}
```

Connect `DATA_DISPATCH -> DISPATCH_BRANCH`, then each `DISPATCH_BRANCH -> branch child node` or directly `DISPATCH_BRANCH -> 结束`.

## Layout Rules

For simple linear flows, auto-layout-style coordinates are fine:

```text
x = 19910
接收数据 y = 19518
数据转换 y = 19754
发送数据 y = 19936
结束 y = 20172
```

For any graph containing `DATA_DISPATCH` or `DISPATCH_BRANCH`, do not click the editor `自动布局` button and do not use the linear auto-layout positions blindly. It can curve and cross branch edges. Place the graph manually:

- Keep the pre-dispatch spine centered: receiver -> convert/mapping/sender -> dispatch.
- Put the dispatch node on the center x.
- Put branch nodes on one horizontal row below dispatch.
- Use branch x offsets around the center. Good defaults:
  - 1 branch: `[0]`
  - 2 branches: `[-220, 220]`
  - 3 branches: `[-286, 0, 286]`
  - 4 branches: `[-420, -140, 140, 420]`
- Put the first node inside each branch directly below that branch node.
- Keep each branch lane vertical and avoid sharing the same y when node heights differ.
- Put the end node below the deepest branch, centered under the overall graph unless only one branch reaches it.
- Add extra vertical room for tall HTTP receiver/sender cards. Typical y gaps:
  - receiver -> convert/mapping: `180-235`
  - convert/mapping -> sender: `180-220`
  - sender -> convert/end: `220-260`
  - dispatch -> branch row: `150`
  - branch -> first branch node: `135-150`

Example 3-branch layout:

```text
centerX = 19716
receiver      (19716, 19924)
convert       (19716, 20130)
dispatch      (19716, 20276)
branch left   (19430, 20426)
branch middle (19716, 20426)
branch right  (20002, 20426)
left sender   (19423, 20563)
left convert  (19428, 20785)
end           (19711, 20940)
```

## Common Flow Patterns

Third-party HTTP callback:

```text
接收数据 -> 数据转换 -> 发送数据(HTTP) -> 结束
```

Database lookup response:

```text
接收数据 -> 数据转换(DBUtil.selectObj/selectOne) -> 结束
```

Dubbo call:

```text
接收数据 -> 数据转换 -> 数据映射(optional) -> 发送数据(Dubbo) -> 结束
```

Dispatch with branch-specific actions:

```text
接收数据 -> 数据转换 -> 数据分流
数据分流 -> 分支1 -> 发送数据(HTTP) -> 数据转换(DBUtil.insert) -> 结束
数据分流 -> 分支2 -> 结束
数据分流 -> 分支3 -> 结束
```

import argparse
import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .server import CONFIG, PREFIX, ROOT, serve


def request(port, route, body=None, status=200):
    url = f'http://127.0.0.1:{port}{PREFIX}{route}'
    opts = {} if body is None else dict(data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    response = None
    try:
        response = urlopen(Request(url, **opts), timeout=5)
    except HTTPError as failure:
        response = failure
    with response:
        if response.status != status:
            raise ValueError(f'{route}：状态码 {response.status}，预期 {status}；{response.read(300)!r}')
        return json.load(response), response.headers


def observe(rows, row_id, field, target):
    result = next((row for row in rows if row['id'] == row_id), None)
    if field is None:
        if result is not None:
            raise ValueError(f'{row_id} 不应出现在结果中')
        return
    actual = result.get(field) if result is not None else None
    ok = isclose(actual, target, abs_tol=1e-8) if type(target) is float and type(actual) in (int,float) else actual == target
    if not ok or result is None or field not in result:
        raise ValueError(f'{row_id}.{field} 为 {actual!r}，应为 {target!r}')


def audit(port, flow):
    review = any(op['id'] == flow and op.get('optional') for op in CONFIG['operations'])
    prefix = 'review-' if review else ''
    data = request(port, prefix+'sample')[0]
    alt = request(port, prefix+'alternate')[0]
    bad = json.loads((ROOT/'examples'/(prefix+'reject.json')).read_text(encoding='utf8'))
    original = request(port,'evaluate',data)[0]
    alternate = request(port,'evaluate',alt)[0]
    request(port,'evaluate',bad,status=400)
    if review:
        request(port, 'seal', bad, status=400)
        baselines = [request(port, 'evaluate', request(port, name)[0])[0] for name in ('sample', 'alternate')]
        for baseline, enhanced in zip(baselines, (original, alternate), strict=True):
            if flow in baseline['outputs'] or any(enhanced['outputs'][k] != v for k,v in baseline['outputs'].items()):
                raise ValueError('复核改变了基础口径')
    if flow in original['outputs']:
        cases = json.loads((ROOT/'examples'/(prefix+'observations.json')).read_text(encoding='utf8'))
        row, key, value, alt_row, alt_key, alt_value = cases[flow]
        observe(original['outputs'][flow],row,key,value)
        observe(alternate['outputs'][flow],alt_row,alt_key,alt_value)
        return
    request(port,'seal',bad,status=400)
    left = request(port,'seal',data)[0]
    again = request(port,'seal',data)[0]
    right = request(port,'seal',alt)[0]
    if not left['created'] or again['created'] or again['sequence'] != left['sequence'] or not right['created']:
        raise ValueError('版本去重或首写失败')
    if len(request(port,'revisions')[0]) != 2:
        raise ValueError('无效及重复记录不应该入库')
    if flow == 'seal':
        observed = request(port,f"packet/{left['digest']}")[0]
        if observed != original:
            raise ValueError('较新的归约改变了历史成果')
    elif flow == 'compare':
        versions = dict(left=left['digest'],right=right['digest'])
        changes = request(port,'compare',versions)[0]
        if not changes['rows'] or request(port,'compare',dict(left=left['digest'],right=left['digest']))[0]['rows']:
            raise ValueError('版本比对没有区分同版及异版')
        other = request(port,'seal',dict(alt,id='不同对象'))[0]
        request(port,'compare',dict(left=left['digest'],right=other['digest']),status=409)
        base = request(port, 'seal', request(port, 'review-sample')[0])[0]
        mixed = request(port, 'compare', dict(left=left['digest'], right=base['digest']))[0]
        stages = {op['label'] for op in CONFIG['operations'] if op.get('optional')}
        if not mixed['rows'] or any(row['stage'] not in stages or row['state'] != 'added' for row in mixed['rows']):
            raise ValueError('旧版比对只应报告新增的复核结果')
        if request(port, f"export/{base['digest']}")[0] != request(port, f"packet/{base['digest']}")[0]:
            raise ValueError('复核信息未完整保存')
    elif flow == 'export':
        payload, headers = request(port,f"export/{left['digest']}")
        if payload != original or 'attachment;' not in headers.get('Content-Disposition',''):
            raise ValueError('导出没有保留原版本或下载头')
        request(port,'export/' + '0'*64,status=404)
    else:
        raise ValueError(f'未知工作流：{flow}')


def audit_acceptance(port):
    data = request(port, 'acceptance-sample')[0]
    alt = request(port, 'acceptance-alternate')[0]
    bad = json.loads((ROOT/'examples'/'acceptance-reject.json').read_text(encoding='utf8'))
    packet = request(port, 'acceptance', data)[0]
    alt_packet = request(port, 'acceptance', alt)[0]
    request(port, 'acceptance', bad, status=400)

    outputs = packet['outputs']
    if packet['subject'] != data['id'] or outputs['unblinding_version'] != '揭盲表-v1':
        raise ValueError('验收批次身份或揭盲版本未保留')
    groups = {row['id']: row for row in outputs['acceptance_groups']}
    levels = {row['id']: row for row in outputs['acceptance_levels']}

    # G1 三条读数全部合格：同一组真值可同时满足重复性与参照核对
    observe(outputs['acceptance_groups'], 'G1', 'state', 'accepted')
    observe(outputs['acceptance_groups'], 'G1', 'joint', 'pass')

    # G3：重复性与参照核对各自都挑得到有利取值（均为 partial），但不存在
    # 同一组真值同时满足两项——联合只能判 partial，组结论为待补而非合格
    observe(outputs['acceptance_groups'], 'G3', 'repeatability', 'partial')
    observe(outputs['acceptance_groups'], 'G3', 'reference', 'partial')
    observe(outputs['acceptance_groups'], 'G3', 'joint', 'partial')
    observe(outputs['acceptance_groups'], 'G3', 'state', 'pending')

    # G2 含缺测与低限（低限按 0 至报告限），缺测不参与证明，证据不足为待补
    g2 = groups['G2']
    if g2['missing'] != ['B06'] or not any(r['code'] == 'B04' and r['report_limit'] == 9 for r in g2['readings']):
        raise ValueError('缺测或低限读数处理错误')
    observe(outputs['acceptance_groups'], 'G2', 'state', 'pending')

    # H2 重复性极差 7.5 必然超限：确证不合格，整档与整批不合格
    observe(outputs['acceptance_groups'], 'H2', 'joint', 'fail')
    observe(outputs['acceptance_groups'], 'H2', 'state', 'rejected')
    observe(outputs['acceptance_levels'], '高浓度档', 'state', 'rejected')
    if outputs['state'] != 'rejected':
        raise ValueError('存在确证不合格组时整批必须判不合格')

    # 同源组的重复读数只能算一个独立组：低浓度档要求 2 组合格，仅 G1 确证合格，
    # G2/G3 待补，故该档不足为待补而不是凑数合格
    low = levels['低浓度档']
    if low['confirmed_pass'] != ['G1'] or low['state'] != 'pending' or low['pending_groups'] != ['G2', 'G3']:
        raise ValueError('同源重复读数被错误计为多个独立组，或待补档位误判')

    # 对照样例全部档位达标
    if alt_packet['outputs']['state'] != 'accepted':
        raise ValueError('对照样例应整体确证合格')

    # 非法输入不落库；相同输入封存只写入一次，且报告可回查锁定读数与揭盲版本
    request(port, 'acceptance-seal', bad, status=400)
    sealed = request(port, 'acceptance-seal', data)[0]
    again = request(port, 'acceptance-seal', data)[0]
    if sealed['created'] is not True or again['created'] is not False:
        raise ValueError('验收成果去重或首写失败')
    saved = request(port, f"packet/{sealed['digest']}")[0]
    if saved['source']['unblinding']['version'] != '揭盲表-v1' or \
            sorted(r['code'] for r in saved['source']['locked']['results']) != outputs['evidence']['locked_codes']:
        raise ValueError('封存成果无法回查锁定读数与揭盲版本')
    if request(port, f"export/{sealed['digest']}")[0] != saved:
        raise ValueError('验收导出未完整保留历史快照')


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]
                        + ['seal', 'compare', 'export', 'acceptance'])
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        with serve(Path(directory)/'observations.sqlite', 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                if args.flow == 'acceptance':
                    audit_acceptance(server.server_port)
                else:
                    audit(server.server_port, args.flow)
            finally:
                server.shutdown()
                thread.join()
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()

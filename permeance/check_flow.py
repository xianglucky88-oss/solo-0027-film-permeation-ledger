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


def audit_steady(port):
    """稳态复核：共存、单起点可行、留出互斥无解、缺证、非法方案拒绝。"""
    expected = {
        'steady-film-a': 'coexistent',
        'steady-film-b': 'coexistent',
        'steady-film-c': 'confirmed_no_solution',
        'steady-film-d': 'confirmed_no_solution',
    }
    for name, overall in expected.items():
        data = json.loads((ROOT / 'examples' / f'{name}.json').read_text(encoding='utf8'))
        packet = request(port, 'evaluate', data)[0]
        steady = packet['outputs']['steady_state']
        if steady['summary']['overall'] != overall:
            raise ValueError(f'{name} 总判定 {steady["summary"]["overall"]}，应为 {overall}')
        # 复核不得改写基础口径
        for key in ('mass', 'flux', 'crossing', 'increment'):
            if key not in packet['outputs']:
                raise ValueError(f'{name} 缺少基础口径 {key}')
    # 膜丙：两个留出点单独都可解释，联合无解
    data = json.loads((ROOT / 'examples' / 'steady-film-c.json').read_text(encoding='utf8'))
    spec = data['review']['steady_state']
    mass = request(port, 'evaluate', data)[0]['outputs']['mass']
    for hold in ('取样五', '取样六'):
        single = json.loads(json.dumps(spec, ensure_ascii=False))
        single['starts'][0]['holdout'] = [{'id': '单留', 'sample': hold}]
        probe = dict(data)
        probe['review'] = dict(steady_state=single)
        row = request(port, 'evaluate', probe)[0]['outputs']['steady_state']['starts'][0]
        if row['state'] != 'feasible':
            raise ValueError(f'膜丙留出点 {hold} 单独应可解释')
    joint = request(port, 'evaluate', data)[0]['outputs']['steady_state']['starts'][0]
    if joint['state'] != 'no_solution' or all(c['feasible'] for c in joint['holdout_checks']):
        raise ValueError('膜丙联合复核应确证无解，并逐点记录失败的留出点')
    # 膜丁：缺证点保留在拟合记录中，不被悄悄删除
    film_d = request(port, 'evaluate',
                     json.loads((ROOT / 'examples' / 'steady-film-d.json').read_text(encoding='utf8')))[0]
    row_d = film_d['outputs']['steady_state']['starts'][0]
    if row_d['state'] != 'evidence_incomplete' or '取样三' not in row_d['fit']:
        raise ValueError('缺证点必须保留且起点判为证据不全')
    # 非法方案被拒绝，且不落库
    bad = json.loads((ROOT / 'examples' / 'steady-reject.json').read_text(encoding='utf8'))
    request(port, 'evaluate', bad, status=400)
    request(port, 'seal', bad, status=400)
    # 无 steady_state 的基础包不产生该输出（向后兼容）
    baseline = request(port, 'evaluate', request(port, 'review-sample')[0])[0]
    if 'steady_state' in baseline['outputs']:
        raise ValueError('未启用稳态复核时不应出现该输出')


def audit(port, flow):
    review = any(op['id'] == flow and op.get('optional') for op in CONFIG['operations'])
    if flow == 'steady_state':
        audit_steady(port)
        return
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


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]+['seal','compare','export'])
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        with serve(Path(directory)/'observations.sqlite', 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                audit(server.server_port,args.flow)
            finally:
                server.shutdown()
                thread.join()
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()

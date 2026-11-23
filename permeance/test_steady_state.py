"""稳态通量与滞后复核的自动化测试（仅用标准库 unittest）。

覆盖：半平面裁剪的可行性、区间不转中点、缺证不删点、留出点共用同一参数、
各留出点单独可解释而联合无解、多个起点共存、滞后互不相容不合并。
"""

import unittest

try:
    from .contract import ContractError
    from .steady_state import analyze_steady_state
except ImportError:  # 允许直接 python3 -I test_steady_state.py 运行
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from permeance.contract import ContractError
    from permeance.steady_state import analyze_steady_state


def point(id_, time, lo, hi, state=None, evidence=None):
    if state is None:
        state = 'known' if lo == hi else 'bounded'
    return dict(id=id_, time=time, lo=lo, hi=hi, state=state,
                evidence=evidence or [id_])


def fit_point(i, sample):
    return dict(id=f'拟合{i}', sample=sample)


def hold_point(i, sample):
    return dict(id=f'复核{i}', sample=sample)


def spec(starts, min_points=3, span=15, slope=(0.05, 3.0), lag=(0.0, 40.0)):
    return dict(slope=dict(lo=slope[0], hi=slope[1]), lag=dict(lo=lag[0], hi=lag[1]),
                min_fit_points=min_points, min_fit_span=span, starts=starts)


class SteadyStateTest(unittest.TestCase):
    def setUp(self):
        # 共线 J=0.32 L=3 的稳态点
        self.collinear = [point('取样一', 5, 0.0, 0.0),
                          point('取样二', 15, 3.84, 3.84),
                          point('取样三', 25, 7.04, 7.04),
                          point('取样四', 35, 10.24, 10.24),
                          point('取样五', 40, 11.84, 11.84),
                          point('取样六', 45, 13.44, 13.44)]

    def test_single_start_recovers_parameters(self):
        starts = [dict(id='起点', sample='取样一',
                       fit=[fit_point(1, '取样三'), fit_point(2, '取样四'), fit_point(3, '取样五')],
                       holdout=[hold_point(1, '取样六')])]
        result = analyze_steady_state(dict(steady_state=spec(starts)), self.collinear, 16)
        row = result['starts'][0]
        self.assertEqual(row['state'], 'feasible')
        self.assertAlmostEqual(row['slope_lo'], 0.32, places=6)
        self.assertAlmostEqual(row['slope_hi'], 0.32, places=6)
        self.assertAlmostEqual(row['lag_lo'], 3.0, places=4)
        self.assertAlmostEqual(row['lag_hi'], 3.0, places=4)
        self.assertTrue(all(check['feasible'] for check in row['holdout_checks']))

    def test_interval_not_reduced_to_midpoint(self):
        # 给拟合点加非对称宽区间；中点拟合会得到不同结果，区间裁剪应保留整块可行域。
        mass = [point('取样一', 5, 0.0, 0.0),
                point('取样二', 15, 3.0, 4.5),
                point('取样三', 25, 6.0, 8.0),
                point('取样四', 35, 9.0, 11.5),
                point('取样五', 40, 11.0, 13.0)]
        starts = [dict(id='起点', sample='取样一',
                       fit=[fit_point(1, '取样二'), fit_point(2, '取样三'), fit_point(3, '取样四')],
                       holdout=[hold_point(1, '取样五')])]
        row = analyze_steady_state(dict(steady_state=spec(starts)), mass, 20)['starts'][0]
        self.assertEqual(row['state'], 'feasible')
        self.assertLess(row['slope_lo'], row['slope_hi'])
        # 证据区间原文保留，未改成中点
        self.assertEqual(row['fit_evidence']['取样二']['lo'], 3.0)
        self.assertEqual(row['fit_evidence']['取样二']['hi'], 4.5)

    def test_missing_evidence_disqualifies_without_dropping(self):
        mass = [point('取样一', 5, 0.0, 0.0), point('取样二', 15, 3.84, 3.84),
                dict(id='取样三', time=25, lo=None, hi=None, state='missing', evidence=['取样三']),
                point('取样四', 35, 10.24, 10.24), point('取样五', 40, 13.0, 13.0)]
        starts = [dict(id='起点', sample='取样一',
                       fit=[fit_point(1, '取样二'), fit_point(2, '取样三'), fit_point(3, '取样四')],
                       holdout=[hold_point(1, '取样五')])]
        row = analyze_steady_state(dict(steady_state=spec(starts)), mass, 20)['starts'][0]
        self.assertEqual(row['state'], 'evidence_incomplete')
        self.assertIn('取样三', row['fit'])  # 缺证点仍保留
        self.assertIsNone(row['slope_lo'])

    def test_holdouts_each_feasible_but_jointly_empty(self):
        # 拟合可行域 J∈[0.4,0.533]；点五只接纳高 J，点六只接纳低 J。
        mass = [point('取样一', 5, 0.0, 0.0),
                point('取样二', 15, 0.0, 6.0), point('取样三', 25, 0.0, 11.0),
                point('取样四', 35, 0.0, 16.0),
                point('取样五', 40, 18.0, 21.338), point('取样六', 45, 13.662, 17.0)]
        fit = [fit_point(1, '取样二'), fit_point(2, '取样三'), fit_point(3, '取样四')]
        joint = [dict(id='丙起点', sample='取样一', fit=fit,
                      holdout=[hold_point(1, '取样五'), hold_point(2, '取样六')])]
        row = analyze_steady_state(dict(steady_state=spec(joint)), mass, 30)['starts'][0]
        self.assertEqual(row['state'], 'no_solution')
        flags = {check['id']: check['feasible'] for check in row['holdout_checks']}
        self.assertEqual(flags, {'取样五': True, '取样六': False})
        # 单独每个留出点都可解释
        for hold in ('取样五', '取样六'):
            one = [dict(id='丙起点', sample='取样一', fit=fit, holdout=[hold_point(1, hold)])]
            single = analyze_steady_state(dict(steady_state=spec(one)), mass, 30)['starts'][0]
            self.assertEqual(single['state'], 'feasible', hold)

    def test_multiple_starts_coexist_with_shared_parameters(self):
        starts = [
            dict(id='甲起点一', sample='取样一',
                 fit=[fit_point(1, '取样三'), fit_point(2, '取样四'), fit_point(3, '取样五')],
                 holdout=[hold_point(1, '取样六')]),
            dict(id='甲起点二', sample='取样二',
                 fit=[fit_point(1, '取样三'), fit_point(2, '取样四'), fit_point(3, '取样五')],
                 holdout=[hold_point(1, '取样六')]),
        ]
        summary = analyze_steady_state(dict(steady_state=spec(starts)), self.collinear, 16)['summary']
        self.assertEqual(summary['overall'], 'coexistent')
        self.assertTrue(summary['compatible'])
        self.assertIsNotNone(summary['shared_parameters'])
        self.assertEqual(summary['feasible_starts'], ['取样一', '取样二'])

    def test_incompatible_lags_are_not_merged(self):
        mass = [point('取样一', 5, 0.5, 0.5), point('取样二', 10, 4.0, 4.0),
                point('取样三', 15, 7.5, 7.5), point('取样四', 20, 11.0, 11.0),
                point('取样五', 30, 4.5, 4.5), point('取样六', 40, 7.5, 7.5),
                point('取样七', 50, 10.5, 10.5)]
        starts = [
            dict(id='短滞后起点', sample='取样一',
                 fit=[fit_point(1, '取样二'), fit_point(2, '取样三')], holdout=[hold_point(1, '取样四')]),
            dict(id='长滞后起点', sample='取样四',
                 fit=[fit_point(1, '取样五'), fit_point(2, '取样六')], holdout=[hold_point(1, '取样七')]),
        ]
        result = analyze_steady_state(
            dict(steady_state=spec(starts, min_points=2, span=5)), mass, 30)
        self.assertEqual(result['summary']['overall'], 'incompatible_lags')
        self.assertIsNone(result['summary']['shared_parameters'])
        self.assertEqual(result['summary']['incompatible_pairs'], [['取样一', '取样四']])
        self.assertTrue(all(row['state'] == 'feasible' for row in result['starts']))

    def test_lag_cannot_be_later_than_start(self):
        # 真实滞后约 33，但起点在 t=15，应被判无解而非放宽约束。
        mass = [point('取样一', 5, 0.0, 0.0), point('取样二', 15, 0.0, 0.0),
                point('取样四', 35, 2.7, 2.7), point('取样五', 40, 9.9, 9.9),
                point('取样六', 45, 17.1, 17.1)]
        starts = [dict(id='起点', sample='取样二',
                       fit=[fit_point(1, '取样四'), fit_point(2, '取样五')],
                       holdout=[hold_point(1, '取样六')])]
        row = analyze_steady_state(
            dict(steady_state=spec(starts, min_points=2, span=5)), mass, 20)['starts'][0]
        self.assertEqual(row['state'], 'no_solution')

    def test_reject_non_increasing_and_unknown_reference(self):
        good = dict(id='起点', sample='取样一',
                    fit=[fit_point(1, '取样三'), fit_point(2, '取样四'), fit_point(3, '取样五')],
                    holdout=[hold_point(1, '取样六')])
        bad_order = dict(id='起点', sample='取样一',
                         fit=[fit_point(1, '取样四'), fit_point(2, '取样三'), fit_point(3, '取样五')],
                         holdout=[hold_point(1, '取样六')])
        with self.assertRaises(ContractError):
            analyze_steady_state(dict(steady_state=spec([bad_order])), self.collinear, 16)
        unknown = dict(good, holdout=[hold_point(1, '不存在')])
        with self.assertRaises(ContractError):
            analyze_steady_state(dict(steady_state=spec([unknown])), self.collinear, 16)

    def test_reject_invalid_slope_range(self):
        starts = [dict(id='起点', sample='取样一',
                       fit=[fit_point(1, '取样三'), fit_point(2, '取样四'), fit_point(3, '取样五')],
                       holdout=[hold_point(1, '取样六')])]
        bad = spec(starts, slope=(3.0, 0.05))
        with self.assertRaises(ContractError):
            analyze_steady_state(dict(steady_state=bad), self.collinear, 16)


if __name__ == '__main__':
    unittest.main()

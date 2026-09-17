import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discovery_agent import Collector, LogReader
from metric_series import latest_metric, series, best_metric
from direct_monitor import collector_command, collector_source, DirectClient


class DirectMonitorTests(unittest.TestCase):
    def test_named_metric_never_falls_back_to_loss(self):
        run = dict(epoch=3, metric_name='loss', current_iou=.2, metrics={'loss':.2},
                   history=[dict(epoch=1, metric_name='mIoU', iou=77),
                            dict(epoch=2, metrics={'mIoU':80, 'loss':.3}),
                            dict(epoch=3, metric_name='loss', iou=.2)])
        self.assertEqual(latest_metric(run, 'mIoU'), (80, 2))
        self.assertEqual(series(run, 'mIoU'), [(1,77),(2,80)])
        self.assertEqual(best_metric(run, 'mIoU'), 80)
        self.assertEqual(latest_metric({'metric_name':'loss','current_iou':.4},'mIoU'), (None,None))

    def test_incremental_read_retains_validation_and_handles_partial_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'train.log'
            log.write_text('max_epochs = 300\nEpoch(train) [1][10/58] loss: 0.4\nEpoch(val) [1][100/100] mIoU: 80.0\n')
            reader = LogReader(log)
            first = reader.read()
            self.assertEqual(first['metrics']['mIoU'],80)
            with log.open('a') as file:
                file.write('Epoch(train) [2][10/58] loss: 0.3\nEpoch(train) [2][20/58] loss: ')
            second = reader.read()
            self.assertEqual(second['metrics'],{'loss':.3,'mIoU':80})
            self.assertEqual(second['metric_epochs']['mIoU'],1)
            self.assertEqual(second['step'],10)
            self.assertNotIn('mIoU',second['history'][-1]['metrics'])
            with log.open('a') as file:
                file.write('0.2\n')
            self.assertEqual(reader.read()['loss'],.2)
            log.write_text('Epoch(train) [1][1/58] loss: 0.9\n')
            self.assertEqual(reader.read()['metrics'],{'loss':.9})

    def test_disappeared_process_is_stopped_not_training(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'train.log'
            log.write_text('max_epochs = 300\nEpoch(train) [2][10/58] loss: 0.4\n')
            collector=Collector()
            item=dict(path=str(log),gpu_ids=['0','1'],pids=['123','124'])
            with patch('discovery_agent.gpu_snapshot',return_value=({'count':2,'gpus':[]},{})):
                with patch('discovery_agent.discover',return_value=[item]):
                    self.assertEqual(collector.snapshot()['runs'][0]['gpu_ids'],['0','1'])
                with patch('discovery_agent.discover',return_value=[]):
                    self.assertEqual(collector.snapshot()['runs'][0]['phase'],'stopped')

    def test_agent_source_compiles_and_host_cannot_be_option(self):
        compile(collector_source(), '<collector>', 'exec')
        self.assertLess(len(collector_command()), 32768)
        self.assertIn('base64', collector_command())
        self.assertEqual(DirectClient('user@host').python_candidates, ('python3', 'python'))
        self.assertEqual(DirectClient('user@host', python='/opt/python').python_candidates, ('/opt/python',))
        with self.assertRaises(ValueError):
            DirectClient('-oProxyCommand=anything')


if __name__ == '__main__':
    unittest.main()

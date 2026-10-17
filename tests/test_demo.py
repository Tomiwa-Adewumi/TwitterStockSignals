import json

import demo


def test_demo_completes_without_network_or_delivery(capsys):
    demo.main()
    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "synthetic-offline-demo"
    assert result["run"]["status"] == "completed"
    assert result["run"]["email_sent"] == 0
    assert result["signal_count"] == 1
    assert result["signals"][0]["ticker"] == "DEMO"

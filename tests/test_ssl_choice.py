"""Whether the server speaks HTTPS: asked for, refused, or worked out.

`server.py` switches HTTPS on by itself when `cert.pem` and `key.pem` sit
beside it, and the dev-server workflow needs those certs (Vite's proxy is
hard-coded to https://localhost:8340). The Electron application loads
`http://127.0.0.1:8340` and cannot follow it there -- measured 2026-09-11, a
server it started on a machine with the certs served TLS, and its http://
health poll saw only a dropped socket. So a launcher that needs plain HTTP
has to be able to say so: `--no-ssl`, which wins over the certs.
"""

import server


def _certs(tmp_path):
    (tmp_path / "cert.pem").write_text("cert")
    (tmp_path / "key.pem").write_text("key")
    return tmp_path


def test_no_flag_still_means_https_when_the_certs_are_there(tmp_path):
    choice = server._arg_parser().parse_args([]).ssl
    assert server._use_ssl(choice, _certs(tmp_path)) is True


def test_no_flag_and_no_certs_is_http(tmp_path):
    choice = server._arg_parser().parse_args([]).ssl
    assert server._use_ssl(choice, tmp_path) is False


def test_no_ssl_wins_over_the_certs(tmp_path):
    choice = server._arg_parser().parse_args(["--no-ssl"]).ssl
    assert server._use_ssl(choice, _certs(tmp_path)) is False


def test_ssl_is_still_how_https_is_asked_for(tmp_path):
    choice = server._arg_parser().parse_args(["--ssl"]).ssl
    assert server._use_ssl(choice, _certs(tmp_path)) is True

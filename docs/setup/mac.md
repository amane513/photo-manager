# Macの構築手順

SDカードとiPhoneからの取り込み、必要時の選別・現像、Amazon Photosへのバックアップを担当するホストの手順である。全体の流れは [README.md](README.md) を参照する。

## 前提

- UbuntuへSSH接続でき、Ubuntu側の主HDDとSMB共有が利用できる（[ubuntu.md](ubuntu.md)）。
- 作業フォルダは `~/Pictures/PhotoWork/` の1つとする。

## 手動で行う作業

- Amazon Photos Desktopのインストール後のログインと、バックアップ対象フォルダの指定。
- 現像ツールのライセンスやアカウントが必要な場合の初回設定。

## 手順

未整備である。rsync over SSHを使う取り込みCLIの導入とSSH接続設定の再構築手順は0006、Amazon Photos Desktopの設定は0008の実施時に追加する。SMBマウントは取り込みに使わず、Amazon Photosと必要時の参照用とする。

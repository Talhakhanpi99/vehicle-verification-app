[app]
title = PRAAL Offline
package.name = praaloffline
package.domain = com.praal
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,txt,html,css,js,db,sqlite
source.exclude_dirs = .buildozer,bin
version = 0.1.0
requirements = python3,flask,sqlite3
orientation = portrait
fullscreen = 1
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.enable_androidx = True
p4a.bootstrap = webview
p4a.port = 5000
log_level = 2
warn_on_root = 0

[buildozer]
log_level = 2

# templates/

cloud-init related assets and future snippets live here. At runtime the panel renders
NoCloud `user-data`, `meta-data` and `network-config` dynamically in
`backend/app/virtualization/cloudinit.py`; downloaded OS cloud images are stored under
the configured `BLUEKVM_TEMPLATE_DIR` (`/var/lib/bluekvm/templates` on a production host)
and never inside this repository.

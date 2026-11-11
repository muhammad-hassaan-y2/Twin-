update_settings(max_parallel_updates=1)

docker_compose(['examples/postgres/docker-compose.yaml'])

docker_build(
    'twin-backend',
    '.',
    target='backend-deps',
    live_update=[sync('.', '/workspace')],
)

docker_build(
    'twin-web',
    '.',
    target='web-deps',
    live_update=[sync('.', '/workspace')],
)

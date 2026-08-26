"""启动入口。

``scripts/start_backend.cmd`` 跑的就是这个文件。路由全在 ``api/routes.py``，
这里只负责把它跑起来——**入口和内容分开**，这样启动不需要读五百行路由。
"""

import os

from api.routes import app

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host=host, port=port, use_reloader=False)

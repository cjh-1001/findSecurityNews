.PHONY: help deploy start stop restart status logs collect push push-am push-pm dashboard clean db-reset

PYTHON ?= python3

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

deploy: ## 一键部署：更新代码、装依赖、启动服务、装 cron
	@echo "==> 拉取最新代码"
	git pull --ff-only
	@echo "==> 安装依赖"
	$(PYTHON) -m pip install -e . --quiet
	@echo "==> 初始化数据库"
	$(PYTHON) run.py init-db
	@echo "==> 启动 RSSHub"
	docker compose up -d rsshub
	@echo "==> 安装 cron 定时任务"
	bash scripts/install_cron.sh
	bash scripts/install_cleanup_cron.sh $${CLEANUP_SCHEDULE:-weekly}
	@echo "==> 部署完成"

start: ## 启动 RSSHub
	docker compose up -d rsshub
	@echo "RSSHub started. http://127.0.0.1:1200"

stop: ## 停止 RSSHub
	docker compose stop rsshub
	@echo "RSSHub stopped."

restart: stop start ## 重启 RSSHub

status: ## 查看服务状态
	@echo "--- RSSHub ---"
	@docker compose ps rsshub 2>/dev/null || echo "未运行"
	@echo ""
	@echo "--- 数据库 ---"
	@$(PYTHON) run.py list --limit 1 2>/dev/null | head -2
	@echo ""
	@echo "--- Cron ---"
	@crontab -l 2>/dev/null | grep findSecurityNews || echo "无定时任务"

logs: ## 查看最近日志
	@echo "--- feishu.log (tail 30) ---"
	@tail -30 logs/feishu.log 2>/dev/null || echo "暂无"
	@echo ""
	@echo "--- cleanup.log (tail 10) ---"
	@tail -10 logs/cleanup.log 2>/dev/null || echo "暂无"

collect: ## 采集文章 + AI 分析
	$(PYTHON) run.py collect --limit 30 --ai

push: ## 推送最新文章
	$(PYTHON) run.py feishu-workflow --window latest --ai

push-am: ## 推送早报
	$(PYTHON) run.py feishu-workflow --window morning --ai

push-pm: ## 推送晚报
	$(PYTHON) run.py feishu-workflow --window evening --ai

dashboard: ## 启动仪表盘 (需要 ENABLE_DASHBOARD=true)
	ENABLE_DASHBOARD=true $(PYTHON) run.py dashboard --host 0.0.0.0 --port 8000

clean: ## 清理临时文件
	rm -rf outputs/site/*
	rm -rf outputs/daily/*
	find logs/ -name "*.log" -type f -mtime +30 -delete
	@echo "清理完成"

db-reset: ## 重建数据库 (危险)
	@echo "警告: 这将删除所有数据！"
	@read -p "确认请输入 yes: " confirm && [ "$$confirm" = "yes" ] || exit 1
	rm -f data/security_news.db
	$(PYTHON) run.py init-db
	@echo "数据库已重建"

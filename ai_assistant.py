import sqlite3
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from helpers import get_db_connection, brl, br_datetime

def get_assistant_response(user_id, message):
    """
    Local AI assistant with NLP rules for financial queries
    """
    message_lower = message.lower().strip()
    
    # Greeting patterns
    if any(word in message_lower for word in ['oi', 'olá', 'hello', 'hi', 'bom dia', 'boa tarde', 'boa noite']):
        return "Olá! Sou o Layon, seu agente financeiro. Posso ajudar com informações sobre suas receitas, despesas, saldo e relatórios. O que gostaria de saber?"
    
    # Help patterns
    if any(word in message_lower for word in ['ajuda', 'help', 'comandos', 'o que você faz']):
        return """Posso ajudar você com:
        
📊 **Consultas de dados:**
- "saldo total" ou "quanto tenho"
- "receitas deste mês" 
- "despesas de hoje"
- "faturamento do mês passado"

📅 **Contas a pagar/receber:**
- "contas a pagar"
- "contas vencendo"
- "próximos vencimentos"
- "contas em atraso"

📈 **Relatórios:**
- "top 5 despesas"
- "maiores gastos"
- "resumo mensal"

⏰ **Períodos:**
- "hoje", "ontem", "esta semana"
- "mês atual", "mês passado"
- "últimos 30 dias"

Experimente perguntar algo como: "Quais contas vencem esta semana?" """

    conn = None
    try:
        conn = get_db_connection()
        
        # Current period calculations
        now_br = datetime.now(ZoneInfo('America/Sao_Paulo'))
        
        # Today
        today_start = now_br.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start.astimezone(timezone.utc).isoformat()
        today_end_utc = now_br.astimezone(timezone.utc).isoformat()
        
        # Yesterday
        yesterday_start = today_start - timedelta(days=1)
        yesterday_start_utc = yesterday_start.astimezone(timezone.utc).isoformat()
        yesterday_end_utc = today_start.astimezone(timezone.utc).isoformat()
        
        # This month
        month_start = now_br.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_utc = month_start.astimezone(timezone.utc).isoformat()
        
        # Last month
        if now_br.month == 1:
            last_month_start = now_br.replace(year=now_br.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            last_month_start = now_br.replace(month=now_br.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        last_month_start_utc = last_month_start.astimezone(timezone.utc).isoformat()
        last_month_end_utc = month_start.astimezone(timezone.utc).isoformat()
        
        # Saldo total
        if any(word in message_lower for word in ['saldo', 'quanto tenho', 'total', 'patrimônio']):
            accounts = conn.execute('''
                SELECT a.initial_balance,
                       COALESCE(SUM(CASE 
                           WHEN e.type = 'receita' THEN e.amount
                           WHEN e.type = 'despesa' THEN -e.amount
                           ELSE 0
                       END), 0) as transactions_total
                FROM accounts a
                LEFT JOIN entries e ON a.id = e.account_id
                WHERE a.user_id = ?
                GROUP BY a.id
            ''', (user_id,)).fetchall()
            
            total_balance = sum(acc['initial_balance'] + acc['transactions_total'] for acc in accounts)
            
            return f"💰 Seu saldo total atual é de **{brl(total_balance)}**.\n\nQue tal conferir suas receitas e despesas do mês? Digite 'resumo mensal'."
        
        # Receitas/Faturamento
        if any(word in message_lower for word in ['receita', 'faturamento', 'ganho', 'entrada']):
            period_query = ""
            period_name = ""
            
            if any(word in message_lower for word in ['hoje', 'dia', 'diário']):
                period_query = f"AND when_utc >= '{today_start_utc}' AND when_utc <= '{today_end_utc}'"
                period_name = "hoje"
            elif any(word in message_lower for word in ['ontem']):
                period_query = f"AND when_utc >= '{yesterday_start_utc}' AND when_utc < '{yesterday_end_utc}'"
                period_name = "ontem"
            elif any(word in message_lower for word in ['mês passado', 'mês anterior']):
                period_query = f"AND when_utc >= '{last_month_start_utc}' AND when_utc < '{last_month_end_utc}'"
                period_name = "no mês passado"
            else:  # Default to current month
                period_query = f"AND when_utc >= '{month_start_utc}'"
                period_name = "neste mês"
            
            result = conn.execute(f'''
                SELECT SUM(amount) as total
                FROM entries 
                WHERE user_id = ? AND type = 'receita' {period_query}
            ''', (user_id,)).fetchone()
            
            total = result['total'] or 0
            
            return f"📈 Suas receitas {period_name} somam **{brl(total)}**.\n\nQuer ver o detalhamento por categoria? Digite 'top receitas'."
        
        # Despesas
        if any(word in message_lower for word in ['despesa', 'gasto', 'saída', 'gastei']):
            period_query = ""
            period_name = ""
            
            if any(word in message_lower for word in ['hoje', 'dia']):
                period_query = f"AND when_utc >= '{today_start_utc}' AND when_utc <= '{today_end_utc}'"
                period_name = "hoje"
            elif any(word in message_lower for word in ['ontem']):
                period_query = f"AND when_utc >= '{yesterday_start_utc}' AND when_utc < '{yesterday_end_utc}'"
                period_name = "ontem"
            elif any(word in message_lower for word in ['mês passado', 'mês anterior']):
                period_query = f"AND when_utc >= '{last_month_start_utc}' AND when_utc < '{last_month_end_utc}'"
                period_name = "no mês passado"
            else:  # Default to current month
                period_query = f"AND when_utc >= '{month_start_utc}'"
                period_name = "neste mês"
            
            result = conn.execute(f'''
                SELECT SUM(amount) as total
                FROM entries 
                WHERE user_id = ? AND type = 'despesa' {period_query}
            ''', (user_id,)).fetchone()
            
            total = result['total'] or 0
            
            return f"💸 Suas despesas {period_name} somam **{brl(total)}**.\n\nPara analisar onde está gastando mais, digite 'top despesas'."
        
        # Top categorias/ranking
        if any(word in message_lower for word in ['top', 'ranking', 'maiores', 'principais']):
            if any(word in message_lower for word in ['despesa', 'gasto']):
                entry_type = 'despesa'
                emoji = '💸'
            else:
                entry_type = 'receita'
                emoji = '📈'
            
            top_categories = conn.execute('''
                SELECT c.name, SUM(e.amount) as total
                FROM entries e
                JOIN categories c ON e.category_id = c.id
                WHERE e.user_id = ? AND e.type = ? AND e.when_utc >= ?
                GROUP BY c.id, c.name
                ORDER BY total DESC
                LIMIT 5
            ''', (user_id, entry_type, month_start_utc)).fetchall()
            
            if not top_categories:
                return f"Ainda não há {entry_type}s registradas neste mês."
            
            response = f"{emoji} **Top 5 {entry_type}s deste mês:**\n\n"
            for i, cat in enumerate(top_categories, 1):
                response += f"{i}. {cat['name']}: {brl(cat['total'])}\n"
            
            response += f"\nQuer mais detalhes? Acesse a seção de Relatórios!"
            return response
        
        # Resumo mensal
        if any(word in message_lower for word in ['resumo', 'resultado', 'balanço', 'mensal']):
            monthly_stats = conn.execute('''
                SELECT 
                    SUM(CASE WHEN type = 'receita' THEN amount ELSE 0 END) as receitas,
                    SUM(CASE WHEN type = 'despesa' THEN amount ELSE 0 END) as despesas
                FROM entries 
                WHERE user_id = ? AND when_utc >= ?
            ''', (user_id, month_start_utc)).fetchone()
            
            receitas = monthly_stats['receitas'] or 0
            despesas = monthly_stats['despesas'] or 0
            resultado = receitas - despesas
            
            status_emoji = "💚" if resultado > 0 else "🔴" if resultado < 0 else "⚪"
            status_text = "positivo" if resultado > 0 else "negativo" if resultado < 0 else "equilibrado"
            
            return f"""📊 **Resumo do mês atual:**

📈 Receitas: {brl(receitas)}
💸 Despesas: {brl(despesas)}
{status_emoji} Resultado: {brl(resultado)} ({status_text})

Quer analisar as categorias que mais impactaram? Digite 'top despesas' ou 'top receitas'."""
        
        # Contas a pagar/receber patterns
        if any(word in message_lower for word in ['conta', 'pagar', 'receber', 'vencimento', 'atraso']):
            period_filter = ""
            status_filter = ""
            type_filter = ""
            title = "Contas"
            
            # Determinar tipo de conta
            if any(word in message_lower for word in ['pagar', 'pago']):
                type_filter = "AND type = 'pagar'"
                title = "Contas a pagar"
            elif any(word in message_lower for word in ['receber', 'recebimento']):
                type_filter = "AND type = 'receber'"
                title = "Contas a receber"
            
            # Determinar período/status
            if any(word in message_lower for word in ['vencendo', 'próxim', 'semana']):
                # Próximos 7 dias
                next_week = (now_br + timedelta(days=7)).astimezone(timezone.utc).isoformat()
                period_filter = f"AND due_date_utc <= '{next_week}'"
                if type_filter:
                    title += " vencendo nos próximos 7 dias"
                else:
                    title = "Contas vencendo nos próximos 7 dias"
            elif any(word in message_lower for word in ['hoje', 'dia']):
                period_filter = f"AND due_date_utc >= '{today_start_utc}' AND due_date_utc <= '{today_end_utc}'"
                if type_filter:
                    title += " que vencem hoje"
                else:
                    title = "Contas que vencem hoje"
            elif any(word in message_lower for word in ['atraso', 'vencid']):
                status_filter = "AND status = 'vencido'"
                if type_filter:
                    title += " em atraso"
                else:
                    title = "Contas em atraso"
            elif any(word in message_lower for word in ['pendente']):
                status_filter = "AND status = 'pendente'"
                if type_filter:
                    title += " pendentes"
                else:
                    title = "Contas pendentes"
            
            bills = conn.execute(f'''
                SELECT description, amount, due_date_utc, status, type
                FROM bills 
                WHERE user_id = ? AND status != 'pago' {type_filter} {period_filter} {status_filter}
                ORDER BY due_date_utc ASC
                LIMIT 10
            ''', (user_id,)).fetchall()
            
            if not bills:
                conn.close()
                return "✅ Não há contas pendentes ou que atendam aos critérios informados."
            
            response = f"📅 **{title}:**\n\n"
            
            for bill in bills:
                due_date = datetime.fromisoformat(bill['due_date_utc'].replace('Z', '+00:00'))
                due_date_br = due_date.astimezone(ZoneInfo('America/Sao_Paulo'))
                days_diff = (due_date_br.date() - now_br.date()).days
                
                # Status emoji
                if bill['status'] == 'vencido':
                    status_emoji = "🔴"
                elif days_diff < 0:
                    status_emoji = "🔴"
                elif days_diff == 0:
                    status_emoji = "⚠️"
                elif days_diff <= 3:
                    status_emoji = "🟡"
                else:
                    status_emoji = "🟢"
                
                # Type emoji
                type_emoji = "💸" if bill['type'] == 'pagar' else "💰"
                
                # Days text
                if days_diff < 0:
                    days_text = f"({abs(days_diff)} dias em atraso)"
                elif days_diff == 0:
                    days_text = "(hoje)"
                elif days_diff == 1:
                    days_text = "(amanhã)"
                else:
                    days_text = f"({days_diff} dias)"
                
                response += f"{status_emoji} {type_emoji} {bill['description']} - {brl(bill['amount'])} {days_text}\n"
            
            conn.close()
            response += "\nQuer mais detalhes? Acesse a seção de Contas a Pagar/Receber!"
            return response
        
        # Default response for unrecognized queries
        conn.close()
        return f"""🤔 Não entendi sua pergunta. Aqui estão algumas sugestões:

💰 "saldo total" - Ver seu patrimônio atual
📈 "receitas deste mês" - Entradas do período
💸 "despesas hoje" - Gastos de hoje
📅 "contas a pagar" - Ver próximos vencimentos
📊 "resumo mensal" - Balanço completo
🏆 "top 5 despesas" - Maiores gastos

Digite **"ajuda"** para ver todos os comandos disponíveis."""
        
    except Exception as e:
        return f"Desculpe, ocorreu um erro ao processar sua solicitação: {str(e)}"
    finally:
        if 'conn' in locals() and conn:
            conn.close()

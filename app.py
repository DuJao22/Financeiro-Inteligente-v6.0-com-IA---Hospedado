import os
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from zoneinfo import ZoneInfo
from helpers import brl, br_datetime, parse_br_currency, parse_br_datetime, get_db_connection, init_db, seed_categories
from ai_assistant import get_assistant_response
import mercadopago

# Configure logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Database configuration (now using SQLite Cloud by default)
# Set USE_SQLITE_CLOUD=false to use local database instead
DB_PATH = os.environ.get("DB_PATH", "./database.db")

def require_login(f):
    """Decorator to require login for routes"""
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, faça login para acessar esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def check_trial_status(user_id):
    """Check if user's trial is active or if they have subscription"""
    conn = get_db_connection()
    user = conn.execute('SELECT trial_start_utc, subscribed FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    if not user:
        return False, "Usuário não encontrado"
    
    if user['subscribed']:
        return True, "Assinatura ativa"
    
    trial_start = datetime.fromisoformat(user['trial_start_utc'].replace('Z', '+00:00'))
    trial_end = trial_start + timedelta(days=7)
    now = datetime.now(timezone.utc)
    
    if now <= trial_end:
        days_left = (trial_end - now).days
        return True, f"Teste grátis - {days_left + 1} dias restantes"
    else:
        return False, "Teste grátis expirado"

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not name or not email or not password:
            flash('Todos os campos são obrigatórios.', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('A senha deve ter pelo menos 6 caracteres.', 'error')
            return render_template('register.html')
        
        try:
            conn = get_db_connection()
            
            # Check if email already exists
            existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
            if existing:
                flash('Este email já está cadastrado.', 'error')
                conn.close()
                return render_template('register.html')
            
            # Create user
            password_hash = generate_password_hash(password)
            trial_start_utc = datetime.now(timezone.utc).isoformat()
            created_at_utc = datetime.now(timezone.utc).isoformat()
            
            cursor = conn.execute(
                'INSERT INTO users (name, email, password_hash, trial_start_utc, subscribed, created_at_utc) VALUES (?, ?, ?, ?, 0, ?)',
                (name, email, password_hash, trial_start_utc, created_at_utc)
            )
            user_id = cursor.lastrowid
            
            # Create default categories for the user
            seed_categories(conn, user_id)
            
            # Create default account
            conn.execute(
                'INSERT INTO accounts (user_id, name, initial_balance) VALUES (?, ?, ?)',
                (user_id, 'Conta Principal', 0.0)
            )
            
            conn.commit()
            conn.close()
            
            session['user_id'] = user_id
            session['user_name'] = name
            flash('Conta criada com sucesso! Bem-vindo ao seu teste grátis de 7 dias.', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            logging.error(f"Error creating user: {e}")
            flash('Erro ao criar conta. Tente novamente.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Email e senha são obrigatórios.', 'error')
            return render_template('login.html')
        
        try:
            conn = get_db_connection()
            user = conn.execute('SELECT id, name, password_hash FROM users WHERE email = ?', (email,)).fetchone()
            conn.close()
            
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['user_name'] = user['name']
                flash('Login realizado com sucesso!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Email ou senha incorretos.', 'error')
                
        except Exception as e:
            logging.error(f"Error during login: {e}")
            flash('Erro ao fazer login. Tente novamente.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout realizado com sucesso.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@require_login
def dashboard():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    try:
        conn = get_db_connection()
        
        # Get accounts with calculated balances
        accounts = conn.execute('''
            SELECT a.id, a.name, a.initial_balance,
                   COALESCE(SUM(CASE 
                       WHEN e.type = 'receita' THEN e.amount
                       WHEN e.type = 'despesa' THEN -e.amount
                       ELSE 0
                   END), 0) as transactions_total
            FROM accounts a
            LEFT JOIN entries e ON a.id = e.account_id
            WHERE a.user_id = ?
            GROUP BY a.id, a.name, a.initial_balance
        ''', (user_id,)).fetchall()
        
        # Calculate total balance
        total_balance = sum(acc['initial_balance'] + acc['transactions_total'] for acc in accounts)
        
        # Get monthly income and expenses
        now = datetime.now(ZoneInfo('America/Sao_Paulo'))
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_utc = month_start.astimezone(timezone.utc).isoformat()
        
        monthly_stats = conn.execute('''
            SELECT 
                SUM(CASE WHEN type = 'receita' THEN amount ELSE 0 END) as receitas,
                SUM(CASE WHEN type = 'despesa' THEN amount ELSE 0 END) as despesas
            FROM entries 
            WHERE user_id = ? AND when_utc >= ?
        ''', (user_id, month_start_utc)).fetchone()
        
        receitas_mes = monthly_stats['receitas'] or 0
        despesas_mes = monthly_stats['despesas'] or 0
        
        # Get recent transactions
        recent_entries = conn.execute('''
            SELECT e.*, a.name as account_name, c.name as category_name
            FROM entries e
            JOIN accounts a ON e.account_id = a.id
            LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.user_id = ?
            ORDER BY e.when_utc DESC
            LIMIT 5
        ''', (user_id,)).fetchall()
        
        # Get upcoming bills
        upcoming_bills = conn.execute('''
            SELECT b.*, a.name as account_name, c.name as category_name
            FROM bills b
            JOIN accounts a ON b.account_id = a.id
            LEFT JOIN categories c ON b.category_id = c.id
            WHERE b.user_id = ? AND b.status = 'pendente'
            ORDER BY b.due_date_utc ASC
            LIMIT 5
        ''', (user_id,)).fetchall()
        
        # Bills summary
        bills_summary = conn.execute('''
            SELECT 
                COUNT(CASE WHEN status = 'pendente' AND type = 'pagar' THEN 1 END) as contas_pagar,
                COUNT(CASE WHEN status = 'pendente' AND type = 'receber' THEN 1 END) as contas_receber,
                COUNT(CASE WHEN status = 'vencido' THEN 1 END) as contas_vencidas
            FROM bills WHERE user_id = ?
        ''', (user_id,)).fetchone()
        
        conn.close()
        
        return render_template('dashboard.html', 
                             trial_active=trial_active,
                             trial_message=trial_message,
                             total_balance=total_balance,
                             receitas_mes=receitas_mes,
                             despesas_mes=despesas_mes,
                             accounts=accounts,
                             recent_entries=recent_entries,
                             upcoming_bills=upcoming_bills,
                             bills_summary=bills_summary,
                             now_utc=datetime.now(timezone.utc).isoformat())
        
    except Exception as e:
        logging.error(f"Error in dashboard: {e}")
        flash('Erro ao carregar dashboard.', 'error')
        return render_template('dashboard.html', 
                             trial_active=trial_active,
                             trial_message=trial_message,
                             total_balance=0,
                             receitas_mes=0,
                             despesas_mes=0,
                             accounts=[],
                             recent_entries=[],
                             upcoming_bills=[],
                             bills_summary=None,
                             now_utc=datetime.now(timezone.utc).isoformat())

@app.route('/lancamentos', methods=['GET', 'POST'])
@require_login
def lancamentos():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if not trial_active:
        flash(f'Acesso restrito: {trial_message}. Assine o plano PRO para continuar.', 'error')
        return redirect(url_for('assinatura'))
    
    if request.method == 'POST':
        try:
            tipo = request.form.get('type')
            amount_str = request.form.get('amount', '').strip()
            note = request.form.get('note', '').strip()
            account_id = request.form.get('account_id')
            category_id = request.form.get('category_id') or None
            when_str = request.form.get('when', '').strip()
            
            # Parse amount
            amount = parse_br_currency(amount_str)
            if amount <= 0:
                flash('Valor deve ser maior que zero.', 'error')
                return redirect(url_for('lancamentos'))
            
            # Parse datetime
            when_utc = parse_br_datetime(when_str)
            
            conn = get_db_connection()
            
            # Verify account belongs to user
            account = conn.execute('SELECT id FROM accounts WHERE id = ? AND user_id = ?', 
                                 (account_id, user_id)).fetchone()
            if not account:
                flash('Conta inválida.', 'error')
                conn.close()
                return redirect(url_for('lancamentos'))
            
            # Create entry
            created_at_utc = datetime.now(timezone.utc).isoformat()
            conn.execute('''
                INSERT INTO entries (user_id, account_id, category_id, type, amount, note, when_utc, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, account_id, category_id, tipo, amount, note, when_utc, created_at_utc))
            
            conn.commit()
            conn.close()
            
            flash('Lançamento criado com sucesso!', 'success')
            return redirect(url_for('lancamentos'))
            
        except Exception as e:
            logging.error(f"Error creating entry: {e}")
            flash('Erro ao criar lançamento. Verifique os dados.', 'error')
    
    # Get user's accounts and categories
    try:
        conn = get_db_connection()
        accounts = conn.execute('SELECT id, name FROM accounts WHERE user_id = ?', (user_id,)).fetchall()
        categories = conn.execute('SELECT id, name, type FROM categories WHERE user_id = ?', (user_id,)).fetchall()
        
        # Get entries with pagination
        page = request.args.get('page', 1, type=int)
        per_page = 20
        offset = (page - 1) * per_page
        
        entries = conn.execute('''
            SELECT e.*, a.name as account_name, c.name as category_name
            FROM entries e
            JOIN accounts a ON e.account_id = a.id
            LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.user_id = ?
            ORDER BY e.when_utc DESC
            LIMIT ? OFFSET ?
        ''', (user_id, per_page, offset)).fetchall()
        
        conn.close()
        
        return render_template('lancamentos.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             accounts=accounts,
                             categories=categories,
                             entries=entries)
        
    except Exception as e:
        logging.error(f"Error in lancamentos: {e}")
        flash('Erro ao carregar lançamentos.', 'error')
        return render_template('lancamentos.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             accounts=[],
                             categories=[],
                             entries=[])

@app.route('/relatorios')
@require_login
def relatorios():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if not trial_active:
        flash(f'Acesso restrito: {trial_message}. Assine o plano PRO para continuar.', 'error')
        return redirect(url_for('assinatura'))
    
    try:
        conn = get_db_connection()
        
        # Get current month data
        now = datetime.now(ZoneInfo('America/Sao_Paulo'))
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_utc = month_start.astimezone(timezone.utc).isoformat()
        
        # Monthly P&L
        monthly_pl = conn.execute('''
            SELECT 
                type,
                SUM(amount) as total
            FROM entries 
            WHERE user_id = ? AND when_utc >= ?
            GROUP BY type
        ''', (user_id, month_start_utc)).fetchall()
        
        # Top categories
        top_categories = conn.execute('''
            SELECT 
                c.name as category_name,
                e.type,
                SUM(e.amount) as total
            FROM entries e
            JOIN categories c ON e.category_id = c.id
            WHERE e.user_id = ? AND e.when_utc >= ?
            GROUP BY c.id, c.name, e.type
            ORDER BY total DESC
            LIMIT 10
        ''', (user_id, month_start_utc)).fetchall()
        
        # Daily cash flow for current month
        daily_flow = conn.execute('''
            SELECT 
                DATE(when_utc) as day,
                SUM(CASE WHEN type = 'receita' THEN amount ELSE 0 END) as receitas,
                SUM(CASE WHEN type = 'despesa' THEN amount ELSE 0 END) as despesas
            FROM entries 
            WHERE user_id = ? AND when_utc >= ?
            GROUP BY DATE(when_utc)
            ORDER BY day
        ''', (user_id, month_start_utc)).fetchall()
        
        conn.close()
        
        return render_template('relatorios.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             monthly_pl=monthly_pl,
                             top_categories=top_categories,
                             daily_flow=daily_flow)
        
    except Exception as e:
        logging.error(f"Error in relatorios: {e}")
        flash('Erro ao carregar relatórios.', 'error')
        return render_template('relatorios.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             monthly_pl=[],
                             top_categories=[],
                             daily_flow=[])

@app.route('/chat')
@require_login
def chat():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    return render_template('chat.html',
                         trial_active=trial_active,
                         trial_message=trial_message)

@app.route('/assinatura', methods=['GET', 'POST'])
@require_login
def assinatura():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if request.method == 'POST':
        # Simulate subscription activation
        try:
            conn = get_db_connection()
            conn.execute('UPDATE users SET subscribed = 1 WHERE id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            flash('Assinatura ativada com sucesso! Bem-vindo ao plano PRO.', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            logging.error(f"Error activating subscription: {e}")
            flash('Erro ao ativar assinatura. Tente novamente.', 'error')
    
    return render_template('assinatura.html',
                         trial_active=trial_active,
                         trial_message=trial_message)

@app.route('/checkout')
@require_login
def checkout():
    user_id = session['user_id']
    plan = request.args.get('plan', 'stand')
    price = float(request.args.get('price', 39.99))
    
    # Mapear nomes dos planos
    plan_names = {
        'stand': 'Stand',
        'intermediario': 'Intermediário',
        'pro': 'Pro'
    }
    
    plan_name = plan_names.get(plan, 'Stand')
    
    # Check if MP token is configured
    mp_access_token = "APP_USR-4883291741868753-082708-f8cb7ba414b18310ef942d53fdde7e26-450933212"
    mp_token_configured = True  # Token is hardcoded for production
    session['mp_token_configured'] = mp_token_configured
    
    # Set token in environment if not already set
    if not os.environ.get("MP_ACCESS_TOKEN"):
        os.environ["MP_ACCESS_TOKEN"] = mp_access_token
    
    return render_template('checkout.html',
                         plan=plan,
                         plan_name=plan_name,
                         price=price,
                         mp_token_configured=mp_token_configured)

@app.route('/checkout', methods=['POST'])
@require_login
def process_checkout():
    user_id = session['user_id']
    
    try:
        # Obter dados do formulário
        plan = request.form.get('plan', 'stand')
        price_str = request.form.get('price', '39.99')
        price = float(price_str) if price_str else 39.99
        payment_method = request.form.get('payment_method')
        mp_token = request.form.get('mp_token')
        customer_name = request.form.get('customer_name')
        customer_email = request.form.get('customer_email')
        customer_phone = request.form.get('customer_phone')
        customer_document = request.form.get('customer_document')
        
        # Validações básicas
        if not all([plan, customer_name, customer_email]):
            flash('Preencha todos os campos obrigatórios.', 'error')
            return redirect(url_for('checkout', plan=plan, price=price))
        
        # Obter token do MP (prioridade: hardcoded > form > env)
        mp_hardcoded_token = "APP_USR-4883291741868753-082708-f8cb7ba414b18310ef942d53fdde7e26-450933212"
        mp_token = mp_hardcoded_token or mp_token or os.environ.get("MP_ACCESS_TOKEN")
        
        # Se token do MP foi fornecido, processar pagamento real
        if mp_token and mp_token.strip():
            try:
                # Configurar SDK do Mercado Pago
                sdk = mercadopago.SDK(mp_token)
                
                # Dados da preferência de pagamento
                preference_data = {
                    "items": [
                        {
                            "title": f"Plano {plan.title() if plan else 'Stand'}",
                            "description": f"Assinatura mensal do plano {plan.title() if plan else 'Stand'}",
                            "quantity": 1,
                            "currency_id": "BRL",
                            "unit_price": price
                        }
                    ],
                    "payer": {
                        "name": customer_name,
                        "email": customer_email
                    },
                    "payment_methods": {
                        "excluded_payment_types": [],
                        "installments": 12
                    },
                    "back_urls": {
                        "success": request.url_root + "payment-success",
                        "failure": request.url_root + "payment-failure",
                        "pending": request.url_root + "payment-pending"
                    },
                    "external_reference": f"user_{user_id}_plan_{plan}"
                }
                
                # Debug: Log dos dados enviados
                logging.info(f"Enviando preference_data: {preference_data}")
                
                # Criar preferência
                preference_response = sdk.preference().create(preference_data)
                
                # Debug: Log da resposta
                logging.info(f"MP Response status: {preference_response['status']}")
                logging.info(f"MP Response: {preference_response}")
                
                preference = preference_response["response"]
                
                if preference_response["status"] == 201:
                    # Redirecionar para o checkout do Mercado Pago
                    return redirect(preference["init_point"])
                else:
                    flash('Erro ao processar pagamento. Verifique o token do Mercado Pago.', 'error')
                    
            except Exception as mp_error:
                logging.error(f"Mercado Pago error: {mp_error}")
                flash('Erro na integração com Mercado Pago. Verifique o token fornecido.', 'error')
        else:
            # Simulação de pagamento para demonstração
            conn = get_db_connection()
            
            # Atualizar usuário com o plano escolhido
            conn.execute('''
                UPDATE users 
                SET subscribed = 1, 
                    subscription_plan = ?,
                    subscription_price = ?,
                    subscription_date = ?
                WHERE id = ?
            ''', (plan, price, datetime.now(timezone.utc).isoformat(), user_id))
            
            conn.commit()
            conn.close()
            
            flash(f'Pagamento simulado com sucesso! Plano {plan.title() if plan else "Stand"} ativado.', 'success')
            return redirect(url_for('dashboard'))
        
    except Exception as e:
        logging.error(f"Error in process_checkout: {e}")
        flash('Erro ao processar checkout. Tente novamente.', 'error')
        # Definir valores padrão em caso de erro
        if 'plan' not in locals():
            plan = 'stand'
        if 'price' not in locals():
            price = 39.99
    
    return redirect(url_for('checkout', plan=plan, price=price))

@app.route('/payment-success')
@require_login
def payment_success():
    # Processar retorno de sucesso do Mercado Pago
    payment_id = request.args.get('payment_id')
    status = request.args.get('status')
    external_reference = request.args.get('external_reference')
    
    if external_reference and 'user_' in external_reference:
        try:
            # Extrair informações da referência externa
            parts = external_reference.split('_')
            user_id = int(parts[1])
            plan = parts[3]
            
            # Ativar assinatura
            conn = get_db_connection()
            conn.execute('''
                UPDATE users 
                SET subscribed = 1, 
                    subscription_plan = ?,
                    subscription_date = ?,
                    mp_payment_id = ?
                WHERE id = ?
            ''', (plan, datetime.now(timezone.utc).isoformat(), payment_id, user_id))
            
            conn.commit()
            conn.close()
            
            flash(f'Pagamento aprovado! Plano {plan.title()} ativado com sucesso.', 'success')
            
        except Exception as e:
            logging.error(f"Error processing payment success: {e}")
            flash('Pagamento aprovado, mas houve erro na ativação. Entre em contato com o suporte.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/payment-failure')
@require_login
def payment_failure():
    flash('Pagamento não foi aprovado. Tente novamente ou escolha outro método.', 'error')
    return redirect(url_for('assinatura'))

@app.route('/payment-pending')
@require_login
def payment_pending():
    flash('Pagamento está pendente. Você receberá uma confirmação quando for aprovado.', 'info')
    return redirect(url_for('dashboard'))

@app.route('/api/assistant', methods=['POST'])
@require_login
def api_assistant():
    user_id = session['user_id']
    
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        
        if not message:
            return jsonify({'status': 'error', 'message': 'Mensagem não pode estar vazia'})
        
        answer = get_assistant_response(user_id, message)
        
        return jsonify({'status': 'ok', 'answer': answer})
        
    except Exception as e:
        logging.error(f"Error in assistant: {e}")
        return jsonify({'status': 'error', 'message': 'Erro interno do servidor'})

@app.route('/contas-pagar-receber', methods=['GET', 'POST'])
@require_login
def contas_pagar_receber():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if not trial_active:
        flash(f'Acesso restrito: {trial_message}. Assine o plano PRO para continuar.', 'error')
        return redirect(url_for('assinatura'))
    
    if request.method == 'POST':
        try:
            bill_type = request.form.get('type')
            amount_str = request.form.get('amount', '').strip()
            description = request.form.get('description', '').strip()
            account_id = request.form.get('account_id')
            category_id = request.form.get('category_id') or None
            due_date_str = request.form.get('due_date', '').strip()
            recurring = request.form.get('recurring', 'nao')
            notes = request.form.get('notes', '').strip()
            
            # Parse amount and due date
            amount = parse_br_currency(amount_str)
            due_date_utc = parse_br_datetime(due_date_str)
            
            if amount <= 0:
                flash('Valor deve ser maior que zero.', 'error')
                return redirect(url_for('contas_pagar_receber'))
            
            if not description:
                flash('Descrição é obrigatória.', 'error')
                return redirect(url_for('contas_pagar_receber'))
            
            conn = get_db_connection()
            
            # Verify account belongs to user
            account = conn.execute('SELECT id FROM accounts WHERE id = ? AND user_id = ?', 
                                 (account_id, user_id)).fetchone()
            if not account:
                flash('Conta inválida.', 'error')
                conn.close()
                return redirect(url_for('contas_pagar_receber'))
            
            # Create bill
            created_at_utc = datetime.now(timezone.utc).isoformat()
            conn.execute('''
                INSERT INTO bills (user_id, account_id, category_id, type, amount, description, 
                                 due_date_utc, status, notes, recurring, created_at_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pendente', ?, ?, ?)
            ''', (user_id, account_id, category_id, bill_type, amount, description, 
                  due_date_utc, notes, recurring, created_at_utc))
            
            conn.commit()
            conn.close()
            
            flash('Conta criada com sucesso!', 'success')
            return redirect(url_for('contas_pagar_receber'))
            
        except Exception as e:
            logging.error(f"Error creating bill: {e}")
            flash('Erro ao criar conta. Verifique os dados.', 'error')
    
    # Get user's accounts and categories
    try:
        conn = get_db_connection()
        accounts = conn.execute('SELECT id, name FROM accounts WHERE user_id = ?', (user_id,)).fetchall()
        categories = conn.execute('SELECT id, name, type FROM categories WHERE user_id = ?', (user_id,)).fetchall()
        
        # Get bills with filters
        status_filter = request.args.get('status', 'all')
        type_filter = request.args.get('type', 'all')
        
        query = '''
            SELECT b.*, a.name as account_name, c.name as category_name
            FROM bills b
            JOIN accounts a ON b.account_id = a.id
            LEFT JOIN categories c ON b.category_id = c.id
            WHERE b.user_id = ?
        '''
        params = [user_id]
        
        if status_filter != 'all':
            query += ' AND b.status = ?'
            params.append(status_filter)
        
        if type_filter != 'all':
            query += ' AND b.type = ?'
            params.append(type_filter)
            
        query += ' ORDER BY b.due_date_utc ASC'
        
        bills = conn.execute(query, params).fetchall()
        
        # Update overdue bills
        now_utc = datetime.now(timezone.utc).isoformat()
        conn.execute('''
            UPDATE bills 
            SET status = 'vencido' 
            WHERE user_id = ? AND status = 'pendente' AND due_date_utc < ?
        ''', (user_id, now_utc))
        conn.commit()
        
        # Get summary stats
        summary = conn.execute('''
            SELECT 
                COUNT(CASE WHEN status = 'pendente' AND type = 'pagar' THEN 1 END) as contas_pagar_pendentes,
                COUNT(CASE WHEN status = 'pendente' AND type = 'receber' THEN 1 END) as contas_receber_pendentes,
                COUNT(CASE WHEN status = 'vencido' THEN 1 END) as contas_vencidas,
                SUM(CASE WHEN status = 'pendente' AND type = 'pagar' THEN amount ELSE 0 END) as valor_pagar,
                SUM(CASE WHEN status = 'pendente' AND type = 'receber' THEN amount ELSE 0 END) as valor_receber
            FROM bills WHERE user_id = ?
        ''', (user_id,)).fetchone()
        
        conn.close()
        
        return render_template('contas_pagar_receber.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             accounts=accounts,
                             categories=categories,
                             bills=bills,
                             summary=summary,
                             status_filter=status_filter,
                             type_filter=type_filter)
        
    except Exception as e:
        logging.error(f"Error in contas_pagar_receber: {e}")
        flash('Erro ao carregar contas.', 'error')
        return render_template('contas_pagar_receber.html',
                             trial_active=trial_active,
                             trial_message=trial_message,
                             accounts=[],
                             categories=[],
                             bills=[],
                             summary=None,
                             status_filter='all',
                             type_filter='all')

@app.route('/bill/<int:bill_id>/pay', methods=['POST'])
@require_login
def pay_bill(bill_id):
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if not trial_active:
        return jsonify({'status': 'error', 'message': 'Acesso restrito'})
    
    try:
        paid_amount_str = request.form.get('paid_amount', '').strip()
        paid_amount = parse_br_currency(paid_amount_str) if paid_amount_str else None
        
        conn = get_db_connection()
        
        # Get bill info
        bill = conn.execute('''
            SELECT * FROM bills WHERE id = ? AND user_id = ? AND status = 'pendente'
        ''', (bill_id, user_id)).fetchone()
        
        if not bill:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Conta não encontrada'})
        
        # Use original amount if no amount specified
        if paid_amount is None:
            paid_amount = bill['amount']
        
        # Mark as paid
        paid_date_utc = datetime.now(timezone.utc).isoformat()
        conn.execute('''
            UPDATE bills 
            SET status = 'pago', paid_date_utc = ?, paid_amount = ?
            WHERE id = ? AND user_id = ?
        ''', (paid_date_utc, paid_amount, bill_id, user_id))
        
        # Create corresponding entry
        entry_type = 'despesa' if bill['type'] == 'pagar' else 'receita'
        conn.execute('''
            INSERT INTO entries (user_id, account_id, category_id, type, amount, note, when_utc, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, bill['account_id'], bill['category_id'], entry_type, 
              paid_amount, f"Pagamento: {bill['description']}", paid_date_utc, paid_date_utc))
        
        conn.commit()
        conn.close()
        
        flash('Conta marcada como paga!', 'success')
        return redirect(url_for('contas_pagar_receber'))
        
    except Exception as e:
        logging.error(f"Error paying bill: {e}")
        flash('Erro ao marcar conta como paga.', 'error')
        return redirect(url_for('contas_pagar_receber'))

@app.route('/export/csv')
@require_login
def export_csv():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if not trial_active:
        flash(f'Acesso restrito: {trial_message}. Assine o plano PRO para continuar.', 'error')
        return redirect(url_for('assinatura'))
    
    try:
        from flask import make_response
        import csv
        from io import StringIO
        
        conn = get_db_connection()
        entries = conn.execute('''
            SELECT e.when_utc, e.type, e.amount, e.note, a.name as account_name, c.name as category_name
            FROM entries e
            JOIN accounts a ON e.account_id = a.id
            LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.user_id = ?
            ORDER BY e.when_utc DESC
        ''', (user_id,)).fetchall()
        conn.close()
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['Data', 'Tipo', 'Valor', 'Descrição', 'Conta', 'Categoria'])
        
        # Data
        for entry in entries:
            when_br = br_datetime(entry['when_utc'])
            valor_br = brl(entry['amount'])
            writer.writerow([
                when_br,
                entry['type'].title(),
                valor_br,
                entry['note'] or '',
                entry['account_name'],
                entry['category_name'] or ''
            ])
        
        output.seek(0)
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=lancamentos_{datetime.now().strftime("%Y%m%d")}.csv'
        
        return response
        
    except Exception as e:
        logging.error(f"Error exporting CSV: {e}")
        flash('Erro ao exportar dados.', 'error')
        return redirect(url_for('relatorios'))

# Make helper functions available in templates
@app.template_global()
def brl(value):
    from helpers import brl as format_brl
    return format_brl(value)

@app.template_global()
def br_datetime(value):
    from helpers import br_datetime as format_br_datetime
    return format_br_datetime(value)

@app.route('/perfil', methods=['GET', 'POST'])
@require_login
def perfil():
    user_id = session['user_id']
    trial_active, trial_message = check_trial_status(user_id)
    
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            
            if not name:
                flash('Nome é obrigatório.', 'error')
                return redirect(url_for('perfil'))
            
            # Atualizar perfil
            conn = get_db_connection()
            conn.execute('UPDATE users SET name = ? WHERE id = ?', (name, user_id))
            conn.commit()
            conn.close()
            
            # Atualizar sessão
            session['user_name'] = name
            
            flash('Perfil atualizado com sucesso!', 'success')
            return redirect(url_for('perfil'))
            
        except Exception as e:
            logging.error(f"Error updating profile: {e}")
            flash('Erro ao atualizar perfil.', 'error')
    
    # Buscar dados do usuário
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    return render_template('perfil.html', user=user, trial_active=trial_active, trial_message=trial_message)

@app.route('/upload-foto', methods=['POST'])
@require_login
def upload_foto():
    user_id = session['user_id']
    
    try:
        if 'foto' not in request.files:
            flash('Nenhuma foto selecionada.', 'error')
            return redirect(url_for('perfil'))
        
        file = request.files['foto']
        if file.filename == '':
            flash('Nenhuma foto selecionada.', 'error')
            return redirect(url_for('perfil'))
        
        # Verificar se é uma imagem
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
        if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
            # Criar diretório se não existir
            upload_folder = 'static/uploads'
            os.makedirs(upload_folder, exist_ok=True)
            
            # Gerar nome único para o arquivo
            import uuid
            filename = f"{user_id}_{uuid.uuid4().hex[:8]}.{file.filename.rsplit('.', 1)[1].lower()}"
            filepath = os.path.join(upload_folder, filename)
            
            # Salvar arquivo
            file.save(filepath)
            
            # Atualizar banco de dados
            photo_url = f"uploads/{filename}"
            conn = get_db_connection()
            conn.execute('UPDATE users SET profile_photo = ? WHERE id = ?', (photo_url, user_id))
            conn.commit()
            conn.close()
            
            flash('Foto de perfil atualizada com sucesso!', 'success')
        else:
            flash('Formato de arquivo não permitido. Use PNG, JPG, JPEG ou GIF.', 'error')
            
    except Exception as e:
        logging.error(f"Error uploading photo: {e}")
        flash('Erro ao fazer upload da foto.', 'error')
    
    return redirect(url_for('perfil'))

@app.route('/chat-assistant', methods=['POST'])
@require_login
def chat_assistant():
    """API endpoint para o assistente flutuante"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        user_id = session.get('user_id')
        
        if not user_message:
            return jsonify({'response': 'Por favor, digite uma mensagem válida.'})
        
        # Usar o assistente existente
        from ai_assistant import get_assistant_response
        assistant_response = get_assistant_response(user_id, user_message)
        
        return jsonify({'response': assistant_response})
        
    except Exception as e:
        logging.error(f"Error in chat assistant: {e}")
        return jsonify({'response': '❌ Desculpe, ocorreu um erro. Tente novamente.'})

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run app
    app.run(host='0.0.0.0', port=5000, debug=True)

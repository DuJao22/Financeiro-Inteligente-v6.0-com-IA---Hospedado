# Overview

This is a Brazilian financial management SaaS application built with Flask. The system provides personal finance tracking with features including transaction management, bills payable/receivable with due dates, financial reporting, AI assistant for financial queries, and subscription-based access control. The application features a modern hamburger sidebar menu for navigation and is designed for Brazilian users with proper localization (Portuguese language, Brazilian currency formatting, and timezone handling).

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Framework**: Flask with Jinja2 templating engine
- **UI Framework**: Bootstrap 5 with Font Awesome icons for consistent styling
- **Navigation**: Modern hamburger sidebar menu with responsive behavior (desktop: always visible, mobile: toggle overlay)
- **Responsive Design**: Mobile-first approach with responsive grid system
- **Localization**: Portuguese language interface with Brazilian currency (R$) and date/time formatting

## Backend Architecture
- **Web Framework**: Flask application with session-based authentication
- **Database**: SQLite for local data storage with custom connection management
- **Authentication**: Password hashing using Werkzeug security utilities
- **Session Management**: Flask sessions with configurable secret key
- **Trial System**: 7-day trial period with subscription upgrade path

## Data Storage
- **Primary Database**: SQLite with custom helper functions for Brazilian localization
- **Schema Design**: Users, transactions (receitas/despesas), accounts, categories, and bills (contas a pagar/receber)
- **Bills Management**: Due date tracking, automatic overdue detection, status management (pendente/pago/vencido)
- **Data Formatting**: Brazilian currency format (R$ 1.000,00) and timezone conversion (America/Sao_Paulo)
- **Connection Pooling**: Custom database connection management with proper cleanup

## AI Assistant
- **Implementation**: Rule-based NLP system for financial queries
- **Capabilities**: Balance inquiries, expense reports, revenue tracking, and period-based analysis
- **Language**: Portuguese language processing with financial domain knowledge
- **Query Types**: Natural language processing for common financial questions

## Access Control
- **Trial System**: 7-day free trial for new users
- **Subscription Model**: Monthly subscription (R$ 100/month) for continued access
- **Route Protection**: Decorator-based authentication for protected endpoints
- **Trial Validation**: Time-based trial expiration checking

## Testing Framework
- **Testing Library**: pytest for unit and integration testing
- **Test Database**: Temporary SQLite database for isolated test execution
- **Coverage Areas**: Currency formatting, datetime handling, and core business logic

# External Dependencies

## Core Dependencies
- **Flask**: Web framework for application structure and routing
- **Werkzeug**: Security utilities for password hashing and authentication
- **Bootstrap 5**: Frontend CSS framework for responsive design
- **Font Awesome**: Icon library for user interface elements

## Python Libraries
- **sqlite3**: Database connectivity and operations
- **zoneinfo**: Timezone handling for Brazilian timezone conversion
- **datetime**: Date and time manipulation for financial calculations
- **pytest**: Testing framework for quality assurance

## Potential Integrations
- **Payment Processing**: Ready for integration with Brazilian payment gateways (PagSeguro, Mercado Pago)
- **Email Services**: Prepared for transactional email integration
- **Analytics**: Structure supports integration with analytics platforms
- **Backup Services**: Database structure allows for cloud backup integration

## Development Tools
- **Environment Variables**: Configuration management for database path and session secrets
- **Logging**: Built-in logging configuration for debugging and monitoring
- **CSV Export**: Data export functionality for external analysis tools
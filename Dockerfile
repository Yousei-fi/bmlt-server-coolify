FROM php:8.3-apache

ENV APACHE_DOCUMENT_ROOT=/var/www/html/main_server/public \
    COMPOSER_ALLOW_SUPERUSER=1 \
    NODE_ENV=production

# Base OS + PHP extensions + Node.js (for building the UI assets)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        libfreetype6-dev \
        libicu-dev \
        libjpeg-dev \
        libpng-dev \
        libzip-dev \
        unzip \
        zip \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install pdo pdo_mysql gd zip intl \
    && a2enmod rewrite headers \
    && rm -rf /var/lib/apt/lists/*

# Set Apache docroot and allow .htaccess for the app
RUN sed -ri 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/000-default.conf /etc/apache2/sites-enabled/000-default.conf \
    && printf '<Directory "%s">\\n    AllowOverride All\\n</Directory>\\n' "${APACHE_DOCUMENT_ROOT}" > /etc/apache2/conf-available/bmlt-override.conf \
    && a2enconf bmlt-override

# Composer
COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer

# Copy source + config
COPY bmlt-server/src/ /var/www/html/main_server/
COPY auto-config.inc.php /var/www/html/auto-config.inc.php

WORKDIR /var/www/html/main_server

# PHP dependencies
RUN composer install --no-dev --optimize-autoloader

# Frontend assets (Svelte/Vite)
RUN npm ci \
    && npm run build \
    && rm -rf node_modules

# Ensure runtime permissions
RUN chown -R www-data:www-data /var/www/html

EXPOSE 80


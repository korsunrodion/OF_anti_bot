import { MigrationInterface, QueryRunner } from 'typeorm';

export class RenameColumnsToSnakeCase1776945600000 implements MigrationInterface {
  async up(queryRunner: QueryRunner): Promise<void> {
    // Rename camelCase columns created by synchronize to snake_case expected by SnakeNamingStrategy.
    // Each rename is conditional so the migration is safe to run on a fresh install too.
    await queryRunner.query(`
      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_input' AND column_name = 'trackingLinkId'
        ) THEN
          ALTER TABLE tracking_links_input RENAME COLUMN "trackingLinkId" TO tracking_link_id;
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_input' AND column_name = 'isProcessed'
        ) THEN
          ALTER TABLE tracking_links_input RENAME COLUMN "isProcessed" TO is_processed;
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'trackingLinkId'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN "trackingLinkId" TO tracking_link_id;
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'userId'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN "userId" TO user_id;
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'subscriptionDate'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN "subscriptionDate" TO subscription_date;
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'riskLevel'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN "riskLevel" TO risk_level;
        END IF;
      END $$;
    `);
  }

  async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_input' AND column_name = 'tracking_link_id'
        ) THEN
          ALTER TABLE tracking_links_input RENAME COLUMN tracking_link_id TO "trackingLinkId";
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_input' AND column_name = 'is_processed'
        ) THEN
          ALTER TABLE tracking_links_input RENAME COLUMN is_processed TO "isProcessed";
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'tracking_link_id'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN tracking_link_id TO "trackingLinkId";
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'user_id'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN user_id TO "userId";
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'subscription_date'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN subscription_date TO "subscriptionDate";
        END IF;

        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'tracking_links_subscriber' AND column_name = 'risk_level'
        ) THEN
          ALTER TABLE tracking_links_subscriber RENAME COLUMN risk_level TO "riskLevel";
        END IF;
      END $$;
    `);
  }
}

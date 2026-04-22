import { MigrationInterface, QueryRunner } from 'typeorm';

export class InitialSchema1776859200000 implements MigrationInterface {
  async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TABLE "tracking_links_input" (
        "id"               varchar   NOT NULL,
        "tracking_link_id" varchar   NOT NULL,
        "is_processed"     boolean   NOT NULL DEFAULT false,
        "subscribers"      jsonb     NOT NULL,
        CONSTRAINT "PK_tracking_links_input" PRIMARY KEY ("id")
      )
    `);

    await queryRunner.query(`
      CREATE TABLE "tracking_links_subscriber" (
        "id"                varchar NOT NULL,
        "tracking_link_id"  varchar NOT NULL,
        "username"          varchar NOT NULL,
        "user_id"           integer NOT NULL,
        "subscription_date" varchar NOT NULL,
        "risk_level"        varchar NOT NULL,
        CONSTRAINT "PK_tracking_links_subscriber" PRIMARY KEY ("id")
      )
    `);
  }

  async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP TABLE "tracking_links_subscriber"`);
    await queryRunner.query(`DROP TABLE "tracking_links_input"`);
  }
}

import { MigrationInterface, QueryRunner } from 'typeorm';

export class Migration1777643848002 implements MigrationInterface {
  name = 'Migration1777643848002';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "avatar_url" character varying`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "header" character varying`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "is_online_matches_subscription" boolean`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "is_reading_messages" boolean`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "is_processed" boolean NOT NULL DEFAULT false`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ALTER COLUMN "risk_level" DROP NOT NULL`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ALTER COLUMN "risk_level" SET NOT NULL`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "is_processed"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "is_reading_messages"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "is_online_matches_subscription"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "header"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "avatar_url"`,
    );
  }
}
